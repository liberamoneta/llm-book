#!/usr/bin/env python3
"""
LLM Book Manager - Dedicato a opere narrative
Basato su BOOK_AGENTS.md

Classificazione russa:
- рассказ (< 30.000) → racconto (5.000-8.000 caratteri)
- повесть (30.000-150.000) → racconto (5.000-8.000 caratteri)
- роман (150.000-800.000) → romanzo (capitolo: 3.000-5.000, finale: 10.000-15.000)
- роман-эпопея (> 800.000) → romanzo_epico (capitolo: 3.000-5.000, finale: 15.000-20.000)

Marker citazioni: >> ... << (supporto multi-riga)

Comandi:
  ingest, update, extract, query, deep, quote, compare, timeline,
  character, theme, translate, article, publish, complete, lint,
  status, list, list-raw, list-books, move, reset-hashes, help, exit

Opzioni ingest:
  --force, -f           Forza la rielaborazione
  --interactive, -i     Modalità interattiva (14 domande)
  --capitolo N          Numero del capitolo (per romanzi)
  --opera "Titolo"      Titolo dell'opera (per collegare capitoli)
  --autore "Nome"       Autore dell'opera (per collegare capitoli)
"""

import os
import re
import json
import shutil
import hashlib
from pathlib import Path
from datetime import datetime
from openai import OpenAI

# ==================== AUTOCOMPLETAMENTO ====================

READLINE_AVAILABLE = False
try:
    import readline
    READLINE_AVAILABLE = True
except ImportError:
    try:
        import pyreadline as readline
        READLINE_AVAILABLE = True
    except ImportError:
        print("⚠️ Autocompletamento non disponibile. Installa: pip install pyreadline")

COMMANDS = [
    'list', 'list-raw', 'list-books', 'move', 'ingest', 'update',
    'extract', 'query', 'deep', 'quote', 'compare', 'timeline',
    'character', 'theme', 'translate', 'article', 'publish', 'complete',
    'lint', 'status', 'list-processed', 'reset-hashes', 'help', 'exit'
]

# ==================== CONFIGURAZIONE ====================

env_file = Path(".env")
api_key = None
if env_file.exists():
    with open(env_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.startswith('DEEPSEEK_API_KEY'):
                api_key = line.split('=')[1].strip()
                break

if not api_key:
    api_key = input("Inserisci la tua DeepSeek API Key: ")

client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

CLIPPINGS = Path("clippings")
RAW = Path("raw")
RAW_ASSETS = RAW / "assets"
BOOK = Path("book")
BOOK_PAGES = BOOK / "pages"
ARTICLES = Path("articles")

for d in [CLIPPINGS, RAW, RAW_ASSETS, BOOK, BOOK_PAGES, ARTICLES]:
    d.mkdir(exist_ok=True)

# ==================== LIMITI ====================
MAX_CHARS_PROSE = 60000
MAX_CHARS_UPDATE = 20000
MAX_CHARS_ANALYSIS = 8000
MAX_CHARS_TRANSLATE = 10000

# ==================== FUNZIONI UTILI ====================

def get_raw_files(text=""):
    try:
        return sorted([f.name for f in RAW.glob(f"{text}*.md") if f.is_file()])
    except:
        return []

def get_book_pages(text=""):
    try:
        return sorted([f.stem for f in BOOK_PAGES.glob(f"{text}*.md") if f.is_file()])
    except:
        return []

def completer(text, state):
    line = readline.get_line_buffer()
    words = line.split()
    
    if len(words) == 0:
        completions = [c for c in COMMANDS if c.startswith(text)]
    else:
        cmd = words[0].lower()
        if cmd in ['move', 'ingest', 'update', 'extract']:
            completions = get_raw_files(text)
        elif cmd in ['query', 'quote', 'compare', 'timeline', 'character', 'theme', 'translate', 'article', 'publish', 'complete']:
            completions = get_book_pages(text)
        else:
            completions = [c for c in COMMANDS if c.startswith(text)]
    
    try:
        return completions[state]
    except IndexError:
        return None

def setup_autocomplete():
    if READLINE_AVAILABLE:
        readline.parse_and_bind("tab: complete")
        readline.set_completer(completer)
        readline.set_completer_delims(' \t\n;')
        print("   ✅ Autocompletamento attivo (usa TAB)")
    else:
        print("   ⚠️ Autocompletamento non disponibile")

def normalize_spaces(text):
    if not text:
        return text
    text = text.replace(' ', '_').replace('-', '_')
    text = re.sub(r'[^\w\u0400-\u04FF\-_.]', '', text)
    return text

def normalize_links(content):
    def replace_link(match):
        return f'[[{normalize_spaces(match.group(1))}]]'
    return re.sub(r'\[\[([^\]]+)\]\]', replace_link, content)

def extract_highlighted_quotes(content):
    """Estrae citazioni con marker >> ... << (supporto multi-riga)"""
    quotes = []
    lines = content.split('\n')
    clean_lines = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        if re.match(r'^>>\s+', line):
            quote_content = re.sub(r'^>>\s+', '', line)
            
            if '<<' in quote_content:
                quote = quote_content.split('<<')[0].strip()
                quotes.append(quote)
                rest = quote_content.split('<<', 1)[1].strip()
                if rest:
                    clean_lines.append(rest)
            else:
                quote_lines = [quote_content]
                i += 1
                found_close = False
                while i < len(lines):
                    next_line = lines[i]
                    if '<<' in next_line:
                        part = next_line.split('<<')[0].strip()
                        if part:
                            quote_lines.append(part)
                        quotes.append('\n'.join(quote_lines).strip())
                        rest = next_line.split('<<', 1)[1].strip()
                        if rest:
                            clean_lines.append(rest)
                        found_close = True
                        break
                    else:
                        quote_lines.append(next_line.strip())
                        i += 1
                if not found_close:
                    quotes.append('\n'.join(quote_lines).strip())
        else:
            clean_lines.append(line)
        
        i += 1
    
    return quotes, '\n'.join(clean_lines)

def detect_language(text):
    sample = text[:1000]
    if any(ord(c) > 0x0400 for c in sample):
        return "ru"
    elif any(c in 'àèéìòù' for c in sample.lower()):
        return "it"
    return "en"

def detect_work_type(content):
    """Rileva il tipo di opera secondo la classificazione russa"""
    content_lower = content.lower()
    length = len(content)
    
    # Escludi teatro (converti a racconto)
    theater_signals = ['явление', 'действие', 'акт', 'сцена', 'реплика',
                       'dialogue', 'act', 'scene', 'enter', 'exit',
                       'personaggio', 'attore', 'copione']
    for signal in theater_signals:
        if signal in content_lower:
            return "racconto"
    
    # Escludi poesia (converti a saggio)
    poetry_signals = ['стих', 'рифм', 'строф', 'poem', 'verse', 'rhyme']
    for signal in poetry_signals:
        if signal in content_lower:
            return "saggio"
    
    # Classificazione per lunghezza (caratteri cirillici)
    if length < 30000:
        return "racconto"
    elif length < 150000:
        return "racconto"
    elif length < 800000:
        return "romanzo"
    else:
        return "romanzo_epico"

def detect_author_from_content(content, lang):
    patterns = {
        "ru": [
            r'Никола[й|я] Васильевич[а]? Гогол[ь|я]',
            r'Лев Толсто[й|го]',
            r'Фёдор Михайлович Достоевски[й|й]',
            r'Антон Павлович Чехов',
            r'Александр Сергеевич Пушкин',
        ],
        "it": [
            r'[Dd]ante Alighieri',
            r'[Ff]rancesco Petrarca',
            r'[Gg]iovanni Boccaccio',
            r'[Ii]talo Calvino',
            r'[Aa]lessandro Manzoni',
        ],
        "en": [
            r'William Shakespeare',
            r'Charles Dickens',
            r'Jane Austen',
            r'Ernest Hemingway',
            r'George Orwell',
        ]
    }
    
    for pattern in patterns.get(lang, []):
        match = re.search(pattern, content)
        if match:
            return normalize_spaces(match.group(0))
    return "Sconosciuto"

def log_activity(operation, details, source=None):
    log_file = BOOK / "log.md"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(f"\n## {operation} @ {timestamp}\n")
        f.write(f"Fonte: {source or 'N/A'}\n")
        f.write(f"Dettagli: {details}\n---\n")

def update_index():
    pages = list(BOOK_PAGES.glob("*.md"))
    
    index = f"""# 📚 Indice del Book

Ultimo aggiornamento: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Statistiche
- Opere totali: {len(pages)}
- Fonti in raw: {len(list(RAW.glob('*.md')))}

## Opere per tipo

"""
    by_type = {"racconto": [], "romanzo": [], "romanzo_epico": [], "saggio": [], "riassunto_completo": [], "other": []}
    for page in pages:
        content = page.read_text(encoding='utf-8')
        work_type = "other"
        for line in content.split('\n')[:10]:
            if line.startswith('type:'):
                work_type = line.split(':', 1)[1].strip().strip('"')
                break
        if work_type in by_type:
            by_type[work_type].append(page)
        else:
            by_type["other"].append(page)
    
    type_names = {
        "racconto": "📖 Racconti (рассказ / повесть)",
        "romanzo": "📚 Romanzi (роман) - capitoli",
        "romanzo_epico": "🏛️ Romanzi epici (роман-эпопея) - capitoli",
        "riassunto_completo": "📘 Riassunti completi",
        "saggio": "✍️ Saggi",
        "other": "📄 Altro"
    }
    
    for t, pages_list in by_type.items():
        if pages_list:
            index += f"\n### {type_names.get(t, t)}\n"
            for page in sorted(pages_list):
                content = page.read_text(encoding='utf-8')
                title = page.stem
                author = ""
                lang = ""
                for line in content.split('\n')[:10]:
                    if line.startswith('title:'):
                        title = line.split(':', 1)[1].strip().strip('"')
                    if line.startswith('author:'):
                        author = line.split(':', 1)[1].strip().strip('"')
                    if line.startswith('language:'):
                        lang = line.split(':', 1)[1].strip().strip('"')
                index += f"- [[{page.stem}]] – {title} ({author}) [{lang}]\n"
    
    (BOOK / "index.md").write_text(index, encoding='utf-8')
    print("   📚 Indice aggiornato")

# ==================== HASH TRACKING ====================

HASH_DB_FILE = Path("book/file_hashes.json")

def load_hash_db():
    if HASH_DB_FILE.exists():
        with open(HASH_DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_hash_db(hash_db):
    with open(HASH_DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(hash_db, f, indent=2, ensure_ascii=False)

def compute_file_hash(file_path):
    content = file_path.read_text(encoding='utf-8')
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            content = parts[2].strip()
    return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]

def is_file_processed(filename, operation="ingest"):
    hash_db = load_hash_db()
    file_path = RAW / filename
    if not file_path.exists():
        return False
    current_hash = compute_file_hash(file_path)
    if filename in hash_db:
        stored = hash_db[filename]
        if stored.get("hash") == current_hash and stored.get("last_operation") == operation:
            return True
    return False

def mark_file_processed(filename, page_name=None, operation="ingest"):
    hash_db = load_hash_db()
    file_path = RAW / filename
    if file_path.exists():
        current_hash = compute_file_hash(file_path)
        hash_db[filename] = {
            "hash": current_hash,
            "page": page_name,
            "last_operation": operation,
            "timestamp": datetime.now().isoformat()
        }
        save_hash_db(hash_db)
        print(f"   🔒 Tracciato: {filename} ({operation}) - hash: {current_hash}")

def get_file_info(filename):
    return load_hash_db().get(filename)

def list_processed():
    hash_db = load_hash_db()
    if not hash_db:
        print("📭 Nessun file elaborato")
        return
    print("\n🔒 FILE ELABORATI")
    print("="*60)
    for filename, info in hash_db.items():
        print(f"   📄 {filename}")
        print(f"      Hash: {info['hash']}")
        print(f"      Pagina: [[{info['page']}]]")
        print(f"      Operazione: {info.get('last_operation', 'ingest')}")
        print(f"      Data: {info['timestamp'][:16]}")
        print()

def reset_processed():
    confirm = input("⚠️ Resettare il database degli hash? Tutti i file verranno rielaborati. (s/n): ")
    if confirm.lower() == 's':
        save_hash_db({})
        print("✅ Database hash resettato")
    else:
        print("❌ Operazione annullata")

# ==================== REGISTRO CAPITOLI ====================

def register_capitolo(title, author, capitolo_num, filename, page_name, force=False):
    """Registra un capitolo nell'indice dell'opera"""
    safe_title = normalize_spaces(title)
    safe_author = normalize_spaces(author)
    opera_id = f"{safe_title}_{safe_author}"
    
    index_file = BOOK / f"{opera_id}_capitoli.json"
    
    capitoli_data = {}
    if index_file.exists():
        with open(index_file, 'r', encoding='utf-8') as f:
            capitoli_data = json.load(f)
    
    if str(capitolo_num) in capitoli_data and not force:
        print(f"   ⚠️ Capitolo {capitolo_num} già registrato per '{title}'")
        return False
    
    capitoli_data[str(capitolo_num)] = {
        "capitolo": capitolo_num,
        "filename": filename,
        "page": page_name,
        "timestamp": datetime.now().isoformat(),
        "title": title,
        "author": author
    }
    
    with open(index_file, 'w', encoding='utf-8') as f:
        json.dump(capitoli_data, f, indent=2, ensure_ascii=False)
    
    print(f"   📌 Capitolo {capitolo_num} registrato per '{title}' di {author}")
    print(f"   📊 Totale capitoli: {len(capitoli_data)}")
    
    return True

def get_opera_capitoli(title, author):
    """Recupera l'indice dei capitoli di un'opera"""
    safe_title = normalize_spaces(title)
    safe_author = normalize_spaces(author)
    opera_id = f"{safe_title}_{safe_author}"
    
    index_file = BOOK / f"{opera_id}_capitoli.json"
    
    if not index_file.exists():
        return None
    
    with open(index_file, 'r', encoding='utf-8') as f:
        return json.load(f)

# ==================== PROMPT COSTRUTTORI ====================

def get_target_length(work_type, is_capitolo=False, is_complete=False):
    """Restituisce il target di caratteri in base al tipo e all'operazione"""
    if work_type == "racconto":
        return "5.000-8.000 caratteri"
    elif work_type == "romanzo":
        if is_capitolo:
            return "3.000-5.000 caratteri"
        elif is_complete:
            return "10.000-15.000 caratteri"
        else:
            return "10.000-15.000 caratteri"
    elif work_type == "romanzo_epico":
        if is_capitolo:
            return "3.000-5.000 caratteri"
        elif is_complete:
            return "15.000-20.000 caratteri"
        else:
            return "15.000-20.000 caratteri"
    else:  # saggio
        return "4.000-6.000 caratteri"

def build_ingest_prompt(content, title, author, lang, work_type, is_capitolo=False, capitolo_num=None, highlighted_quotes=None):
    """Costruisce il prompt per il riassunto"""
    lang_name = {"ru": "russo", "it": "italiano", "en": "inglese"}.get(lang, "originale")
    
    quotes_section = ""
    if highlighted_quotes:
        quotes_section = "\n\n## 📌 CITAZIONI EVIDENZIATE\n\n"
        for q in highlighted_quotes:
            quotes_section += f"- {q}\n"
        quotes_section += "\n"
    
    if lang == "ru":
        language_instruction = "⚠️ Scrivi il riassunto COMPLETAMENTE in RUSSO."
    elif lang == "it":
        language_instruction = "⚠️ Scrivi il riassunto COMPLETAMENTE in ITALIANO."
    else:
        language_instruction = "⚠️ Scrivi il riassunto COMPLETAMENTE in INGLESE."
    
    target_length = get_target_length(work_type, is_capitolo, False)
    
    if is_capitolo:
        return f"""Sei un critico letterario. Crea un RIASSUNTO DEL CAPITOLO {capitolo_num} di quest'opera.

{language_instruction}

⚠️ LUNGHEZZA TARGET: {target_length}
⚠️ Descrivi solo gli eventi di QUESTO capitolo.
⚠️ NON superare la lunghezza indicata.

TESTO DEL CAPITOLO:
{content[:MAX_CHARS_PROSE]}

OPERA: {title}
AUTORE: {author}
TIPO: {work_type}
{quotes_section}

FORMATO:

# {title} - Capitolo {capitolo_num}

> *[Citazione più significativa del capitolo]*

## 📖 Riassunto del capitolo

[Eventi principali di questo capitolo, {target_length}]

## 💬 Citazioni

- *«[Citazione 1]»*
- *«[Citazione 2]»*

## 🔗 Collegamenti

- [[{normalize_spaces(author)}]]
- [[{normalize_spaces(title)}_Capitolo_{capitolo_num-1 if capitolo_num > 1 else 1}]]
- [[{normalize_spaces(title)}_Capitolo_{capitolo_num+1}]]
- [[{normalize_spaces(title)}_riassunto_completo]]

⚠️ Mantieni la lingua {lang_name}."""
    
    else:
        return f"""Sei un critico letterario. Crea un RIASSUNTO COMPLETO e DETTAGLIATO di quest'opera.

{language_instruction}

⚠️ LUNGHEZZA TARGET: {target_length}
⚠️ REQUISITI:
1. Descrivi TUTTA la trama: inizio, sviluppo, climax, conclusione, morale
2. Includi 4-6 citazioni importanti
3. Crea link [[...]] per personaggi e autore
4. NON troncare il finale

TESTO:
{content[:MAX_CHARS_PROSE]}

AUTORE: {author}
TITOLO: {title}
TIPO: {work_type}
{quotes_section}

FORMATO OBBLIGATORIO:

# {title}

> *[Citazione più significativa]*

## 📜 Сведения

| Поле | Деталь |
|------|--------|
| **Автор** | [[{normalize_spaces(author)}]] |
| **Тип** | {work_type} |
| **Язык** | {lang_name} |

## 👥 Персонажи

- **[[Nome_1]]** — [descrizione]
- **[[Nome_2]]** — [descrizione]
(minimo 4, massimo 8)

## 📖 Содержание

### Часть первая: [Titolo]

[2-3 paragrafi]

### Часть вторая: [Titolo]

[3-4 paragrafi]

### Часть третья: [Titolo]

[2-3 paragrafi]

### Заключение

[Morale, messaggio finale]

## 💬 Цитаты

- *«[Citazione 1]»* — [[Personaggio]]
- *«[Citazione 2]»*
- *«[Citazione 3]»* — [[Personaggio]]

## 🎯 Темы

1. **[Tema 1]** — [spiegazione]
2. **[Tema 2]** — [spiegazione]
3. **[Tema 3]** — [spiegazione]

## 🔗 Связанные страницы

- [[{normalize_spaces(author)}]]
- [[Personaggio_1]]
- [[Personaggio_2]]

⚠️ Mantieni la lingua {lang_name}. NON superare {target_length}."""

def build_complete_prompt(title, author, work_type, riassunti_capitoli):
    """Costruisce il prompt per il riassunto finale del romanzo"""
    target_length = get_target_length(work_type, is_capitolo=False, is_complete=True)
    
    if work_type == "romanzo_epico":
        lang_name = "russo"
    else:
        lang_name = "russo"
    
    return f"""Sei un critico letterario. Crea un RIASSUNTO FINALE COMPLETO dell'intero romanzo.

⚠️ LUNGHEZZA TARGET: {target_length}
⚠️ LINGUA: RUSSO

RIASSUNTI DEI CAPITOLI (in ordine):
{chr(10).join(riassunti_capitoli)[:20000]}

TITOLO: {title}
AUTORE: {author}
TIPO: {work_type}
CAPITOLI: {len(riassunti_capitoli)}

FORMATO:

# {title} - Riassunto completo

> *[Citazione più significativa del romanzo]*

## 📜 Scheda

| Поле | Деталь |
|------|--------|
| **Автор** | [[{normalize_spaces(author)}]] |
| **Тип** | {work_type} |
| **Capitoli** | {len(riassunti_capitoli)} |

## 👥 Personaggi principali

[Lista dei personaggi con descrizioni]

## 📖 Riassunto completo

### Часть первая: Inizio

[Eventi dei primi capitoli]

### Часть вторая: Sviluppo

[Eventi centrali]

### Часть третья: Conclusione

[Eventi finali, climax, risoluzione]

### Заключение

[Morale dell'autore]

## 💬 Citazioni principali

- *«Citazione 1»* — [[Personaggio]]
- *«Citazione 2»*

## 🎯 Temi principali

1. **[Tema 1]** — spiegazione
2. **[Tema 2]** — spiegazione
3. **[Tema 3]** — spiegazione

## 🔗 Связанные страницы

- [[{normalize_spaces(author)}]]
- [[{normalize_spaces(title)}_Capitolo_1]]
- [[{normalize_spaces(title)}_Capitolo_{len(riassunti_capitoli)}]]

⚠️ Mantieni la lingua RUSSO. NON troncare il finale."""

def build_article_prompt(riassunto, title, author, rating, target_lang="it"):
    """Costruisce il prompt per l'articolo Substack"""
    return f"""Sei un critico letterario che scrive per Substack. Trasforma il seguente RIASSUNTO in un ARTICOLO DI APPROFONDIMENTO coinvolgente.

⚠️ LUNGHEZZA: 8.000-12.000 caratteri (per racconto) o 12.000-25.000 (per romanzo)
⚠️ LINGUA: {target_lang.upper()}
⚠️ TONO: Personale, critico, accessibile

RIASSUNTO DELL'OPERA:
{riassunto[:10000]}

TITOLO: {title}
AUTORE: {author}
VOTO: {rating}/5

FORMATO OBBLIGATORIO:

# [Titolo accattivante]

> *[Sottotitolo]*

*Pubblicato il [data] | Tempo di lettura: X minuti*

---

## ✍️ L'incipit del critico

[Cari lettori, introduzione personale]

**Voto: [★/5]** – [giudizio sintetico]

---

## 📚 Scheda dell'opera

| | |
|---|---|
| **Titolo** | {title} |
| **Autore** | {author} |

---

## 🎭 Trama in pillole

[4-6 frasi, solo eventi essenziali]

---

## 🔍 Analisi critica

### [Primo tema]

[Analisi, 2-3 paragrafi]

### [Secondo tema]

[Analisi, 2-3 paragrafi]

### [Terzo tema]

[Analisi, 2-3 paragrafi]

---

## 💬 Le citazioni che mi hanno colpito

> *«Citazione 1»*

[Commento]

> *«Citazione 2»*

[Commento]

---

## 🎯 Temi universali

1. **[Tema 1]** – spiegazione
2. **[Tema 2]** – spiegazione

---

## 📖 Perché leggerlo oggi

[Attualità dell'opera, 2-3 paragrafi]

---

## ⭐ Il mio giudizio

| Aspetto | Voto |
|---------|------|
| Trama | ★★★★☆ |
| Personaggi | ★★★★★ |
| Scrittura | ★★★★☆ |
| Attualità | ★★★★★ |

**Voto complessivo: {rating}/5**

[Giudizio finale]

---

## 🔗 Collegamenti con altre opere

- **[Opera 1]** (Autore) – collegamento

---

*Iscriviti alla newsletter per non perdere i prossimi approfondimenti.*

© 2026 – Critica Letteraria Indipendente

⚠️ Mantieni la lingua {target_lang}. Sii personale e coinvolgente."""

# ==================== INTERACTIVE INGEST ====================

def ask_work_type(auto_type):
    print("\n❓ [1/14] Di che tipo di opera si tratta?")
    print(f"   Rilevato automaticamente: {auto_type}")
    print("   1) Racconto (рассказ / повесть)")
    print("   2) Romanzo (роман)")
    print("   3) Romanzo epico (роман-эпопея)")
    print("   4) Saggio (essay)")
    choice = input("   → Scegli [1-4] o Invio: ").strip()
    type_map = {"1": "racconto", "2": "romanzo", "3": "romanzo_epico", "4": "saggio"}
    return type_map.get(choice, auto_type)

def ask_title(auto_title):
    print("\n❓ [2/14] Qual è il titolo?")
    print(f"   Rilevato: {auto_title}")
    title = input("   → Titolo (Invio per mantenere): ").strip()
    return title if title else auto_title

def ask_author(auto_author):
    print("\n❓ [3/14] Chi è l'autore?")
    print(f"   Rilevato: {auto_author}")
    author = input("   → Autore (Invio per mantenere): ").strip()
    return author if author else auto_author

def ask_language(auto_lang):
    lang_names = {"ru": "russo", "it": "italiano", "en": "inglese"}
    print("\n❓ [4/14] In che lingua è scritta?")
    print(f"   Rilevato: {lang_names.get(auto_lang, auto_lang)}")
    print("   1) Russo (ru)")
    print("   2) Italiano (it)")
    print("   3) Inglese (en)")
    choice = input("   → Scegli [1-3] o Invio: ").strip()
    lang_map = {"1": "ru", "2": "it", "3": "en"}
    return lang_map.get(choice, auto_lang)

def ask_read_status():
    print("\n❓ [5/14] Hai letto quest'opera?")
    print("   1) Sì, completamente")
    print("   2) Sì, solo in parte")
    print("   3) No, ancora non letta")
    print("   4) In corso di lettura")
    choice = input("   → Scegli [1-4]: ").strip()
    status_map = {"1": "completed", "2": "partial", "3": "unread", "4": "reading"}
    return status_map.get(choice, "unknown")

def ask_rating():
    print("\n❓ [6/14] Da 1 a 5 stelle, che voto le dai?")
    print("   ★☆☆☆☆ (1) - Scarso")
    print("   ★★☆☆☆ (2) - Sufficiente")
    print("   ★★★☆☆ (3) - Buono")
    print("   ★★★★☆ (4) - Molto buono")
    print("   ★★★★★ (5) - Eccellente")
    choice = input("   → Scegli [1-5] o 0 per saltare: ").strip()
    if choice in ["1", "2", "3", "4", "5"]:
        return int(choice)
    return None

def ask_personal_entities():
    print("\n❓ [7/14] Quali entità (nomi propri) vuoi associare?")
    print("   (personaggi, luoghi, autori, opere correlate)")
    print("   Esempio: Piskarev, Pirogov, Schiller, Gogol, Pietroburgo")
    entities = input("   → Entities (separate da virgola): ").strip()
    if entities:
        return [e.strip().replace(' ', '_') for e in entities.split(',')]
    return []

def ask_personal_tags():
    print("\n❓ [8/14] Quali tag (categorie) vuoi associare?")
    print("   (generi, keywords, stati)")
    print("   Esempio: racconto, russian, classic, read_2026")
    tags = input("   → Tags (separate da virgola): ").strip()
    if tags:
        return [t.strip().lower().replace(' ', '_') for t in tags.split(',')]
    return []

def ask_manual_links():
    print("\n❓ [9/14] Vuoi creare link manuali ad altre pagine del book?")
    print("   (es: [[Gogol_Nikolaj]], [[Pietroburgo]])")
    links = input("   → Link (separati da virgola): ").strip()
    if links:
        pattern = r'\[\[([^\]]+)\]\]'
        found = re.findall(pattern, links)
        if found:
            return [normalize_spaces(l) for l in found]
        return [normalize_spaces(l.strip()) for l in links.split(',')]
    return []

def ask_genre():
    print("\n❓ [10/14] A quale genere letterario appartiene?")
    print("   Esempi: realismo fantastico, commedia, tragedia, giallo")
    genre = input("   → Genere: ").strip()
    return genre if genre else None

def ask_personal_notes():
    print("\n❓ [11/14] Vuoi aggiungere una nota generale su quest'opera?")
    notes = input("   → Nota (Invio per saltare): ").strip()
    return notes if notes else None

def ask_highlights():
    print("\n❓ [12/14] Cosa ti ha colpito di più?")
    highlights = input("   → Risposta: ").strip()
    return highlights if highlights else None

def ask_manual_quotes(existing_quotes):
    print(f"\n❓ [13/14] Nel file raw hai usato >> ... << per evidenziare {len(existing_quotes)} citazioni.")
    print("   Vuoi aggiungerne altre manualmente?")
    add = input("   → s/n: ").strip().lower()
    manual_quotes = []
    if add == 's':
        print("   Inserisci le citazioni (riga vuota per terminare):")
        print("   Formato: >> Testo della citazione << — Personaggio")
        while True:
            quote = input("   >> ").strip()
            if not quote:
                break
            if quote.endswith('<<'):
                quote = quote[:-2].strip()
            manual_quotes.append(quote)
    return manual_quotes

def ask_publish_article():
    print("\n❓ [14/14] Vuoi generare un articolo/blog post da questo riassunto?")
    print("   1) Sì, formato Markdown")
    print("   2) Sì, formato HTML")
    print("   3) No")
    choice = input("   → Scegli [1-3]: ").strip()
    if choice == "1":
        return "markdown"
    elif choice == "2":
        return "html"
    return None

def interactive_metadata(filename, auto_type, auto_title, auto_author, auto_lang, existing_quotes):
    print("\n" + "="*60)
    print("📖 MODALITÀ INTERATTIVA - Inserisci i metadati")
    print("   (IGNORO il frontmatter del file raw, uso le tue scelte)")
    print("="*60)
    
    work_type = ask_work_type(auto_type)
    title = ask_title(auto_title)
    author = ask_author(auto_author)
    language = ask_language(auto_lang)
    read_status = ask_read_status()
    rating = ask_rating()
    personal_entities = ask_personal_entities()
    personal_tags = ask_personal_tags()
    manual_links = ask_manual_links()
    genre = ask_genre()
    personal_notes = ask_personal_notes()
    highlights = ask_highlights()
    manual_quotes = ask_manual_quotes(existing_quotes)
    publish_format = ask_publish_article()
    
    # Per i romanzi, conferma titolo e autore (obbligatori per collegare i capitoli)
    if work_type in ["romanzo", "romanzo_epico"]:
        print("\n   ⚠️ Per i romanzi, titolo e autore verranno usati per")
        print("      collegare automaticamente tutti i capitoli.")
        confirm_title = input(f"   → Confermi il titolo '{title}'? (s/n): ").strip().lower()
        if confirm_title != 's':
            title = input("   → Inserisci il titolo corretto: ").strip()
        confirm_author = input(f"   → Confermi l'autore '{author}'? (s/n): ").strip().lower()
        if confirm_author != 's':
            author = input("   → Inserisci l'autore corretto: ").strip()
    
    print("\n" + "="*60)
    print("✅ RIEPILOGO METADATI:")
    print(f"   Tipo: {work_type}")
    print(f"   Titolo: {title}")
    print(f"   Autore: {author}")
    print(f"   Lingua: {language}")
    print(f"   Stato lettura: {read_status}")
    print(f"   Voto: {rating if rating else 'non specificato'}")
    print(f"   Entities: {personal_entities if personal_entities else 'nessuna'}")
    print(f"   Tags: {personal_tags if personal_tags else 'nessuno'}")
    print(f"   Link manuali: {manual_links if manual_links else 'nessuno'}")
    print(f"   Genere: {genre if genre else 'non specificato'}")
    print(f"   Note: {personal_notes if personal_notes else 'nessuna'}")
    print(f"   Highlights: {highlights if highlights else 'nessuno'}")
    print(f"   Citazioni manuali: {len(manual_quotes)}")
    print(f"   Pubblicazione: {publish_format if publish_format else 'no'}")
    print("="*60)
    
    confirm = input("\n✅ Procedi con questi dati? (s/n): ").strip().lower()
    if confirm != 's':
        print("❌ Operazione annullata")
        return None
    
    return {
        "work_type": work_type,
        "title": title,
        "author": author,
        "language": language,
        "read_status": read_status,
        "rating": rating,
        "personal_entities": personal_entities,
        "personal_tags": personal_tags,
        "manual_links": manual_links,
        "genre": genre,
        "personal_notes": personal_notes,
        "highlights": highlights,
        "manual_quotes": manual_quotes,
        "publish_format": publish_format
    }

# ==================== INGEST ====================

def ingest(filename, force=False, interactive=False, capitolo_num=None, opera_title=None, opera_author=None):
    src = RAW / filename
    if not src.exists():
        print(f"❌ {filename} non trovato in raw/")
        return

    if not force and is_file_processed(filename, "ingest"):
        info = get_file_info(filename)
        print(f"\n⏭️ SKIP: {filename} già elaborato")
        if info and info.get("page"):
            print(f"   Pagina: [[{info['page']}]]")
        print("   Usa 'ingest --force' per forzare")
        return
    elif force:
        print("   ⚡ Forzatura: rielaborazione")

    print(f"\n📚 INGEST: {filename}")
    content = src.read_text(encoding='utf-8')
    
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            content = parts[2].strip()
    
    highlighted_quotes, clean_content = extract_highlighted_quotes(content)
    if highlighted_quotes:
        print(f"   📌 Estratte {len(highlighted_quotes)} citazioni evidenziate (>> ... <<)")
    
    # Rilevazione automatica (solo se NON in modalità interattiva)
    auto_type = detect_work_type(clean_content)
    auto_lang = detect_language(clean_content)
    auto_author = detect_author_from_content(clean_content, auto_lang)
    auto_title = filename.replace('.md', '')
    for line in clean_content.split('\n')[:10]:
        if line.startswith('# '):
            auto_title = line[2:].strip()
            break
    
    work_type = auto_type
    title = auto_title
    author = auto_author
    lang = auto_lang
    extra_metadata = {}
    
    if interactive:
        metadata = interactive_metadata(filename, auto_type, auto_title, auto_author, auto_lang, highlighted_quotes)
        if metadata is None:
            return
        
        work_type = metadata["work_type"]
        title = metadata["title"]
        author = metadata["author"]
        lang = metadata["language"]
        
        if metadata["manual_quotes"]:
            highlighted_quotes.extend(metadata["manual_quotes"])
        
        auto_entities = re.findall(r'\[\[([^\]]+)\]\]', clean_content[:1000])
        all_entities = list(set(auto_entities + metadata["personal_entities"]))[:8]
        
        auto_tags = [work_type, "riassunto"]
        auto_tags.append("russian" if lang == "ru" else "italian" if lang == "it" else "english")
        all_tags = list(set(auto_tags + metadata["personal_tags"]))[:8]
        
        extra_metadata = {
            "read_status": metadata["read_status"],
            "rating": metadata["rating"],
            "genre": metadata["genre"],
            "personal_notes": metadata["personal_notes"],
            "highlights": metadata["highlights"],
            "publish_format": metadata["publish_format"],
            "manual_links": metadata["manual_links"]
        }
    else:
        all_entities = re.findall(r'\[\[([^\]]+)\]\]', clean_content[:1000])[:8]
        all_entities = [normalize_spaces(e) for e in set(all_entities)]
        all_tags = [work_type, "riassunto"]
        all_tags.append("russian" if lang == "ru" else "italian" if lang == "it" else "english")
        all_tags = list(set(all_tags))[:6]
    
    # Se è un romanzo e abbiamo un capitolo, usa il nome specifico
    if work_type in ["romanzo", "romanzo_epico"] and capitolo_num:
        safe_title = normalize_spaces(opera_title or title)
        page_name = f"{safe_title}_Capitolo_{capitolo_num}_{work_type}"
        is_capitolo = True
    else:
        safe_title = normalize_spaces(title)
        page_name = f"{safe_title}_{work_type}"
        is_capitolo = False
    
    print(f"   📖 Tipo: {work_type}")
    print(f"   🌐 Lingua: {lang}")
    print(f"   ✍️ Autore: {author}")
    print(f"   📌 Titolo: {title}")
    if capitolo_num:
        print(f"   📖 Capitolo: {capitolo_num}")
    print(f"   📏 Lunghezza: {len(clean_content)} caratteri")
    
    prompt = build_ingest_prompt(clean_content, title, author, lang, work_type, is_capitolo, capitolo_num, highlighted_quotes)
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=4000
    )
    
    summary_content = response.choices[0].message.content
    summary_content = normalize_links(summary_content)
    
    if extra_metadata.get("highlights"):
        summary_content = f"> 💡 **Cosa mi ha colpito:** {extra_metadata['highlights']}\n\n---\n\n{summary_content}"
    
    if extra_metadata.get("manual_links"):
        links_section = "\n\n## 🔗 Collegamenti\n"
        for link in extra_metadata["manual_links"]:
            if not link.startswith('[['):
                link = f"[[{link}]]"
            links_section += f"- {link}\n"
        summary_content += links_section
    
    page_path = BOOK_PAGES / f"{page_name}.md"
    counter = 1
    while page_path.exists():
        page_name = f"{safe_title}_{work_type}_{counter}"
        page_path = BOOK_PAGES / f"{page_name}.md"
        counter += 1
    
    entities_str = json.dumps(all_entities, ensure_ascii=False) if all_entities else "[]"
    tags_str = json.dumps(all_tags, ensure_ascii=False)
    word_count = len(summary_content.split())
    
    frontmatter = f"""---
title: "{title}"
type: {work_type}
language: {lang}
author: "{author}"
source: [{filename}]
created: {datetime.now().date()}
updated: {datetime.now().date()}
word_count: {word_count}
tags: {tags_str}
entities: {entities_str}
status: "completato"
"""
    
    if extra_metadata.get("read_status"):
        frontmatter += f'read_status: "{extra_metadata["read_status"]}"\n'
    if extra_metadata.get("rating"):
        frontmatter += f'rating: {extra_metadata["rating"]}\n'
    if extra_metadata.get("genre"):
        frontmatter += f'genre: "{extra_metadata["genre"]}"\n'
    if extra_metadata.get("personal_notes"):
        frontmatter += f'personal_notes: "{extra_metadata["personal_notes"]}"\n'
    if extra_metadata.get("publish_format"):
        frontmatter += f'publish_format: "{extra_metadata["publish_format"]}"\n'
    if capitolo_num:
        frontmatter += f'capitolo: {capitolo_num}\n'
        frontmatter += f'opera_title: "{opera_title or title}"\n'
    
    frontmatter += "---\n\n"
    page_path.write_text(frontmatter + summary_content, encoding='utf-8')
    
    mark_file_processed(filename, page_name, "ingest")
    
    # Registra il capitolo se è un romanzo
    if work_type in ["romanzo", "romanzo_epico"] and capitolo_num:
        register_capitolo(opera_title or title, author, capitolo_num, filename, page_name, force)
    
    print(f"   ✅ Riassunto creato: book/pages/{page_name}.md")
    print(f"   📊 Parole: {word_count}")
    print(f"   🏷️ Tags: {len(all_tags)}")
    print(f"   🔗 Entities: {len(all_entities)}")
    if highlighted_quotes:
        print(f"   💬 Citazioni evidenziate: {len(highlighted_quotes)}")
    if extra_metadata.get("personal_notes"):
        print(f"   📝 Note personali: {len(extra_metadata['personal_notes'])} caratteri")
    
    # Genera articolo se richiesto
    if extra_metadata.get("publish_format"):
        article_name = f"{datetime.now().date()}_{safe_title}"
        if extra_metadata["publish_format"] == "markdown":
            (ARTICLES / f"{article_name}.md").write_text(f"# {title}\n\n{summary_content}", encoding='utf-8')
            print(f"   📄 Articolo generato: articles/{article_name}.md")
        elif extra_metadata["publish_format"] == "html":
            html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>{title}</title>
<style>body{{font-family:Arial;max-width:800px;margin:0 auto;padding:20px;line-height:1.6;}}</style>
</head>
<body>{summary_content}</body>
</html>"""
            (ARTICLES / f"{article_name}.html").write_text(html, encoding='utf-8')
            print(f"   📄 Articolo generato: articles/{article_name}.html")
    
    log_activity("INGEST", f"Creato riassunto da {filename} (tipo: {work_type})", filename)
    update_index()
    
    return page_name

# ==================== UPDATE ====================

def update_existing(filename, force=False, capitolo_num=None, opera_title=None, opera_author=None):
    src = RAW / filename
    if not src.exists():
        print(f"❌ {filename} non trovato in raw/")
        return

    if not force and is_file_processed(filename, "update"):
        print(f"\n⏭️ SKIP UPDATE: {filename} già usato")
        print("   Usa 'update --force' per forzare")
        return
    elif force:
        print("   ⚡ Forzatura: update")

    print(f"\n🔄 UPDATE: {filename}")
    content = src.read_text(encoding='utf-8')
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            content = parts[2].strip()
    
    quotes, clean_content = extract_highlighted_quotes(content)
    if quotes:
        print(f"   📌 Estratte {len(quotes)} citazioni evidenziate (>> ... <<)")
    
    # Se abbiamo capitolo, titolo e autore, cerca l'opera esistente
    if capitolo_num and opera_title and opera_author:
        capitoli_data = get_opera_capitoli(opera_title, opera_author)
        
        if not capitoli_data:
            print(f"   ⚠️ Nessuna opera trovata per '{opera_title}' di {opera_author}")
            print(f"   Esegui prima 'ingest' del capitolo 1 con --capitolo 1")
            return
        
        # Trova il primo capitolo per ottenere il nome della pagina
        first_num = min(capitoli_data.keys(), key=int)
        first_info = capitoli_data[first_num]
        target_name = first_info["page"]
        
        print(f"   🔗 Opera trovata: '{opera_title}' di {opera_author}")
        print(f"   📖 Collegamento al capitolo {first_num}: [[{target_name}]]")
        
        # Registra il nuovo capitolo
        register_capitolo(opera_title, opera_author, capitolo_num, filename, f"{normalize_spaces(opera_title)}_Capitolo_{capitolo_num}_romanzo", force)
        
        # Crea il riassunto del capitolo
        ingest(filename, force, interactive=False, capitolo_num=capitolo_num, opera_title=opera_title, opera_author=opera_author)
        
        print(f"   ✅ Capitolo {capitolo_num} aggiunto all'opera '{opera_title}'")
        return
    
    # Fallback: modalità normale
    pages = list(BOOK_PAGES.glob("*.md"))
    if not pages:
        print("   ⚠️ Nessuna pagina nel book. Esegui prima 'ingest'")
        return
    
    target_page = pages[0]
    target_name = target_page.stem
    
    old_full = target_page.read_text(encoding='utf-8')
    old_body = old_full
    old_lang = "en"
    old_title = target_name
    
    if old_full.startswith('---'):
        parts = old_full.split('---', 2)
        if len(parts) >= 3:
            old_body = parts[2].strip()
            for line in parts[1].split('\n'):
                if line.startswith('language:'):
                    old_lang = line.split(':', 1)[1].strip().strip('"').strip("'")
                if line.startswith('title:'):
                    old_title = line.split(':', 1)[1].strip().strip('"')
    
    lang_instruction = "Mantieni il testo in RUSSO" if old_lang == "ru" else "Mantieni in ITALIANO" if old_lang == "it" else "Mantieni in ENGLISH"
    
    quotes_note = ""
    if quotes:
        quotes_note = "\n\nNUOVE CITAZIONI:\n" + "\n".join([f"- {q}" for q in quotes])
    
    merge_prompt = f"""Fondi queste due versioni.

PAGINA ESISTENTE:
{old_body[:MAX_CHARS_UPDATE]}

NUOVA FONTE:
{clean_content[:MAX_CHARS_UPDATE]}
{quotes_note}

{lang_instruction}

1. Mantieni info da entrambe
2. Risolvi contraddizioni (privilegia nuova fonte)
3. AGGIUNGI le nuove citazioni
4. Mantieni la lingua della pagina esistente

Restituisci SOLO il contenuto aggiornato."""
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": merge_prompt}],
        temperature=0.3,
        max_tokens=4000
    )
    
    merged = response.choices[0].message.content
    merged = normalize_links(merged)
    
    entities = re.findall(r'\[\[([^\]]+)\]\]', merged)
    entities = [normalize_spaces(e) for e in set(entities)][:8]
    entities_str = json.dumps(entities, ensure_ascii=False) if entities else "[]"
    
    tags = ["aggiornato", "russian" if old_lang == "ru" else "italian" if old_lang == "it" else "english"]
    tags_str = json.dumps(list(set(tags)), ensure_ascii=False)
    
    new_frontmatter = f"""---
title: "{old_title}"
type: {detect_work_type(merged)}
language: {old_lang}
author: "{detect_author_from_content(merged, old_lang)}"
source: [{filename}]
created: {datetime.now().date()}
updated: {datetime.now().date()}
word_count: {len(merged.split())}
tags: {tags_str}
entities: {entities_str}
status: "aggiornato"
---

"""
    target_page.write_text(new_frontmatter + merged, encoding='utf-8')
    mark_file_processed(filename, target_name, "update")
    print(f"   ✅ Pagina aggiornata: {target_name}")
    log_activity("UPDATE", f"Aggiornata [[{target_name}]] con {filename}", filename)
    update_index()

# ==================== COMPLETE ====================

def complete_summary(opera_title, opera_author=None):
    """Genera il riassunto finale del romanzo da tutti i capitoli"""
    if not opera_author:
        opera_author = input("   → Inserisci l'autore dell'opera: ").strip()
    
    capitoli_data = get_opera_capitoli(opera_title, opera_author)
    
    if not capitoli_data:
        print(f"❌ Nessun capitolo trovato per '{opera_title}' di {opera_author}")
        return
    
    print(f"\n📚 Generazione riassunto completo per: {opera_title}")
    print(f"   Capitoli trovati: {len(capitoli_data)}")
    
    # Raccogli i riassunti dei capitoli in ordine
    riassunti_capitoli = []
    work_type = None
    author = opera_author
    
    for num in sorted(capitoli_data.keys(), key=int):
        info = capitoli_data[num]
        page_path = BOOK_PAGES / f"{info['page']}.md"
        if page_path.exists():
            content = page_path.read_text(encoding='utf-8')
            if content.startswith('---'):
                parts = content.split('---', 2)
                if len(parts) >= 3:
                    content = parts[2].strip()
            
            # Estrai il tipo dal frontmatter
            if not work_type:
                page_content = page_path.read_text(encoding='utf-8')
                if page_content.startswith('---'):
                    parts = page_content.split('---', 2)
                    if len(parts) >= 3:
                        for line in parts[1].split('\n'):
                            if line.startswith('type:'):
                                work_type = line.split(':', 1)[1].strip().strip('"')
                                break
            
            riassunti_capitoli.append(f"## Capitolo {num}\n{content[:4000]}")
            print(f"   ✅ Letto capitolo {num}")
    
    if not riassunti_capitoli:
        print("❌ Nessun riassunto di capitolo valido trovato")
        return
    
    if not work_type:
        work_type = "romanzo"
    
    prompt = build_complete_prompt(opera_title, author, work_type, riassunti_capitoli)
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=5000
    )
    
    complete_content = response.choices[0].message.content
    complete_content = normalize_links(complete_content)
    
    safe_title = normalize_spaces(opera_title)
    page_name = f"{safe_title}_riassunto_completo"
    page_path = BOOK_PAGES / f"{page_name}.md"
    
    word_count = len(complete_content.split())
    
    frontmatter = f"""---
title: "{opera_title} - Riassunto completo"
type: riassunto_completo
language: ru
author: "{author}"
source: aggregato_da_capitoli
created: {datetime.now().date()}
updated: {datetime.now().date()}
word_count: {word_count}
capitoli: {len(riassunti_capitoli)}
status: "completato"
---

"""
    page_path.write_text(frontmatter + complete_content, encoding='utf-8')
    
    print(f"   ✅ Riassunto completo creato: book/pages/{page_name}.md")
    print(f"   📊 Parole: {word_count}")
    print(f"   📖 Capitoli aggregati: {len(riassunti_capitoli)}")
    
    log_activity("COMPLETE", f"Creato riassunto completo per {opera_title} da {len(riassunti_capitoli)} capitoli", None)
    update_index()
    
    return page_name

# ==================== TRANSLATE ====================

def translate_page(page_name, target_lang="it"):
    page_path = BOOK_PAGES / f"{page_name}.md"
    if not page_path.exists():
        print(f"❌ Pagina {page_name} non trovata")
        return
    
    print(f"\n🌐 TRADUCI IN {target_lang.upper()}: {page_name}")
    
    content = page_path.read_text(encoding='utf-8')
    body = content
    original_lang = "en"
    
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            for line in parts[1].split('\n'):
                if line.startswith('language:'):
                    original_lang = line.split(':', 1)[1].strip().strip('"').strip("'")
                    break
            body = parts[2].strip()
    
    lang_map = {'it': 'italiano', 'ru': 'russo', 'en': 'inglese'}
    
    prompt = f"""Traduci quest'opera in {lang_map[target_lang]}.

TESTO ORIGINALE ({lang_map[original_lang]}):
{body[:MAX_CHARS_TRANSLATE]}

Mantieni la struttura markdown e i link [[...]].
Traduci i titoli delle sezioni.
Restituisci SOLO il testo tradotto."""
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    
    translated = response.choices[0].message.content
    translated_name = f"{page_name}_{target_lang}"
    translated_path = BOOK_PAGES / f"{translated_name}.md"
    counter = 1
    while translated_path.exists():
        translated_name = f"{page_name}_{target_lang}_{counter}"
        translated_path = BOOK_PAGES / f"{translated_name}.md"
        counter += 1
    
    frontmatter = f"""---
title: "{page_name}"
type: translation
language: {target_lang}
translated_from: {page_name} ({original_lang})
created: {datetime.now().date()}
tags: ["traduzione"]
status: "tradotto"
---

"""
    translated_path.write_text(frontmatter + translated, encoding='utf-8')
    print(f"   ✅ Traduzione creata: book/pages/{translated_name}.md")
    log_activity("TRANSLATE", f"Tradotta [[{page_name}]] in {target_lang}", None)
    update_index()

# ==================== ARTICLE ====================

def generate_article(page_name, format="substack", target_lang="it"):
    page_path = BOOK_PAGES / f"{page_name}.md"
    if not page_path.exists():
        print(f"❌ Pagina {page_name} non trovata")
        return
    
    print(f"\n✍️ GENERA ARTICOLO: {page_name}")
    print(f"   Formato: {format}")
    print(f"   Lingua target: {target_lang}")
    
    content = page_path.read_text(encoding='utf-8')
    body = content
    title = page_name
    author = "Sconosciuto"
    rating = "N/A"
    
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            for line in parts[1].split('\n'):
                if line.startswith('title:'):
                    title = line.split(':', 1)[1].strip().strip('"')
                if line.startswith('author:'):
                    author = line.split(':', 1)[1].strip().strip('"')
                if line.startswith('rating:'):
                    rating = line.split(':', 1)[1].strip()
            body = parts[2].strip()
    
    # Se necessario, traduci il corpo in italiano
    current_lang = detect_language(body)
    if current_lang != target_lang:
        print(f"   🌐 Traduzione da {current_lang} a {target_lang}...")
        translate_prompt = f"""Traduci il seguente testo da {current_lang} a {target_lang}.
        Mantieni la struttura markdown.
        
        TESTO:
        {body[:8000]}"""
        
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": translate_prompt}],
            temperature=0.3
        )
        body = response.choices[0].message.content
    
    prompt = build_article_prompt(body, title, author, rating, target_lang)
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
        max_tokens=5000
    )
    
    article_content = response.choices[0].message.content
    article_content = article_content.replace("[data]", datetime.now().strftime("%d %B %Y"))
    
    safe_title = normalize_spaces(title)
    article_name = f"{datetime.now().date()}_{safe_title}_articolo"
    article_path = ARTICLES / f"{article_name}.md"
    
    frontmatter = f"""---
title: "{title} - Articolo di approfondimento"
type: article
platform: {format}
created: {datetime.now().date()}
source_page: {page_name}
language: {target_lang}
---

"""
    article_path.write_text(frontmatter + article_content, encoding='utf-8')
    
    print(f"\n   ✅ Articolo generato: {article_path}")
    print(f"   📝 Pronto per essere copiato su {format}.com")
    
    log_activity("ARTICLE", f"Generato articolo per {page_name}", None)
    
    return article_path

# ==================== PUBLISH ====================

def publish(page_name, target_lang="it", platform="substack"):
    print(f"\n📝 PUBBLICA SU {platform.upper()}: {page_name}")
    print(f"   Lingua target: {target_lang}")
    
    # Verifica se esiste già una traduzione
    translated_name = f"{page_name}_{target_lang}"
    translated_path = BOOK_PAGES / f"{translated_name}.md"
    
    if not translated_path.exists():
        print(f"   🌐 Traduzione da {detect_language(page_name)} a {target_lang}...")
        translate_page(page_name, target_lang)
    
    # Genera articolo
    article_path = generate_article(translated_name, platform, target_lang)
    
    print(f"\n   ✅ Pubblicazione completata!")
    print(f"   📄 Articolo: {article_path}")
    print(f"   📋 Copia il contenuto su {platform}.com")
    
    return article_path

# ==================== ALTRI COMANDI ====================

def extract(filename, force=False):
    # ... (codice esistente invariato)
    src = RAW / filename
    if not src.exists():
        print(f"❌ {filename} non trovato in raw/")
        return

    if not force and is_file_processed(filename, "extract"):
        print(f"\n⏭️ SKIP EXTRACT: {filename} già elaborato")
        print("   Usa 'extract --force' per forzare")
        return
    elif force:
        print("   ⚡ Forzatura: extract")

    print(f"\n📌 EXTRACT: {filename}")
    content = src.read_text(encoding='utf-8')
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            content = parts[2].strip()
    
    quotes, clean_content = extract_highlighted_quotes(content)
    if quotes:
        print(f"   📌 Estratte {len(quotes)} citazioni evidenziate")
    
    title = filename.replace('.md', '')
    for line in clean_content.split('\n'):
        if line.startswith('# '):
            title = line[2:].strip()
            break
    
    work_type = detect_work_type(clean_content)
    lang = detect_language(clean_content)
    
    quotes_text = ""
    if quotes:
        quotes_text = "\n\nCitazioni evidenziate:\n" + "\n".join([f"- {q}" for q in quotes])
    
    prompt = f"""Estrai SOLO l'essenziale da quest'opera {work_type}.

TESTO:
{clean_content[:MAX_CHARS_PROSE//2]}
{quotes_text}

CREA:

# {title} - Punti chiave

## TL;DR (massimo 3 righe)

## Personaggi principali (massimo 5)

## Trama in 5 punti
1.
2.
3.
4.
5.

## Citazione più significativa

Sii ultra-conciso. Nessuna analisi."""
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    
    wiki = response.choices[0].message.content
    wiki = normalize_links(wiki)
    
    safe_title = normalize_spaces(title)[:40]
    page_name = f"{safe_title}_essenziale"
    page_path = BOOK_PAGES / f"{page_name}.md"
    counter = 1
    while page_path.exists():
        page_name = f"{safe_title}_essenziale_{counter}"
        page_path = BOOK_PAGES / f"{page_name}.md"
        counter += 1
    
    frontmatter = f"""---
title: "{title} - Punti chiave"
type: essential
language: {lang}
created: {datetime.now().date()}
source: [{filename}]
category: Essenziali
tags: ["riassunto", "essenziale"]
entities: []
status: "essenziale"
---

"""
    page_path.write_text(frontmatter + wiki, encoding='utf-8')
    mark_file_processed(filename, page_name, "extract")
    print(f"   ✅ Versione essenziale: book/pages/{page_name}.md")
    log_activity("EXTRACT", f"Creato essenziale da {filename}", filename)
    update_index()
    return page_name

def query(question):
    print(f"\n❓ {question}")
    pages = list(BOOK_PAGES.glob("*.md"))
    if not pages:
        print("   Book vuoto.")
        return
    
    context = ""
    for p in pages[:20]:
        txt = p.read_text(encoding='utf-8')
        if txt.startswith('---'):
            parts = txt.split('---', 2)
            if len(parts) >= 3:
                txt = parts[2].strip()
        context += f"\n## [[{p.stem}]]\n{txt[:MAX_CHARS_ANALYSIS//2]}\n"
    
    prompt = f"""Rispondi basandoti SOLO sul book.

BOOK:
{context}

DOMANDA: {question}

- Usa solo info del book
- Cita le opere con [[titolo]]
- Rispondi nella lingua della domanda

Risposta:"""
    
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1
    )
    print("\n" + "="*60)
    print(resp.choices[0].message.content)
    print("="*60)
    log_activity("QUERY", f"Domanda: {question[:100]}", None)

def deep_search(question):
    print(f"\n🌐 RICERCA WEB: {question}")
    prompt = f"""Cerca informazioni aggiornate in rete su questo argomento letterario.

DOMANDA: {question}

Restituisci risposta strutturata con fonti."""
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    print("\n" + "="*60)
    print("🌐 RISULTATI:")
    print(response.choices[0].message.content)
    print("="*60)
    log_activity("DEEP_SEARCH", f"Ricerca web: {question[:100]}", None)

def quote(page_name, character=None):
    page_path = BOOK_PAGES / f"{page_name}.md"
    if not page_path.exists():
        print(f"❌ Pagina {page_name} non trovata")
        return
    
    content = page_path.read_text(encoding='utf-8')
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            content = parts[2].strip()
    
    prompt = f"""Estrai le citazioni più significative da quest'opera.

OPERA:
{content[:MAX_CHARS_ANALYSIS]}

{"Personaggio specifico: " + character if character else ""}

Restituisci in formato markdown:
- Citazione — Personaggio (atto/scena/capitolo)"""
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    print("\n" + "="*60)
    print(f"💬 CITAZIONI DA {page_name}")
    print(response.choices[0].message.content)
    print("="*60)

def compare(work1, work2):
    path1 = BOOK_PAGES / f"{work1}.md"
    path2 = BOOK_PAGES / f"{work2}.md"
    if not path1.exists() or not path2.exists():
        print("❌ Una o entrambe le opere non trovate")
        return
    
    content1 = path1.read_text(encoding='utf-8')
    content2 = path2.read_text(encoding='utf-8')
    
    if content1.startswith('---'):
        parts = content1.split('---', 2)
        if len(parts) >= 3:
            content1 = parts[2].strip()
    if content2.startswith('---'):
        parts = content2.split('---', 2)
        if len(parts) >= 3:
            content2 = parts[2].strip()
    
    prompt = f"""Confronta queste due opere letterarie.

OPERA 1: {work1}
{content1[:MAX_CHARS_ANALYSIS]}

OPERA 2: {work2}
{content2[:MAX_CHARS_ANALYSIS]}

STRUTTURA:
- Temi comuni
- Differenze principali
- Personaggi
- Stile narrativo
- Conclusione"""
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    print("\n" + "="*60)
    print(f"📖 CONFRONTO: {work1} vs {work2}")
    print(response.choices[0].message.content)
    print("="*60)

def timeline(page_name):
    page_path = BOOK_PAGES / f"{page_name}.md"
    if not page_path.exists():
        print(f"❌ Pagina {page_name} non trovata")
        return
    
    content = page_path.read_text(encoding='utf-8')
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            content = parts[2].strip()
    
    prompt = f"""Estrai la timeline degli eventi.

OPERA:
{content[:MAX_CHARS_ANALYSIS]}

Restituisci in formato:
## Timeline
1. [Evento 1]
2. [Evento 2]..."""
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    print("\n" + "="*60)
    print(f"📅 TIMELINE: {page_name}")
    print(response.choices[0].message.content)
    print("="*60)

def character(page_name, char_name=None):
    page_path = BOOK_PAGES / f"{page_name}.md"
    if not page_path.exists():
        print(f"❌ Pagina {page_name} non trovata")
        return
    
    content = page_path.read_text(encoding='utf-8')
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            content = parts[2].strip()
    
    prompt = f"""Analizza i personaggi di quest'opera.

OPERA:
{content[:MAX_CHARS_ANALYSIS]}

{"Personaggio specifico: " + char_name if char_name else "Elenco tutti i personaggi"}

Restituisci per ogni personaggio:
- Nome
- Ruolo
- Caratteristiche
- Evoluzione"""
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    print("\n" + "="*60)
    print(f"🎭 PERSONAGGI: {page_name}")
    print(response.choices[0].message.content)
    print("="*60)

def theme(page_name):
    page_path = BOOK_PAGES / f"{page_name}.md"
    if not page_path.exists():
        print(f"❌ Pagina {page_name} non trovata")
        return
    
    content = page_path.read_text(encoding='utf-8')
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            content = parts[2].strip()
    
    prompt = f"""Analizza i temi principali di quest'opera.

OPERA:
{content[:MAX_CHARS_ANALYSIS]}

Per ogni tema:
- Nome
- Manifestazione
- Esempi dal testo
- Significato"""
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    print("\n" + "="*60)
    print(f"🎯 TEMI: {page_name}")
    print(response.choices[0].message.content)
    print("="*60)

def lint():
    print("\n🔍 LINT: analisi book...")
    pages = list(BOOK_PAGES.glob("*.md"))
    issues = []
    
    all_links = set()
    for p in pages:
        txt = p.read_text(encoding='utf-8')
        all_links.update(re.findall(r'\[\[([^\]]+)\]\]', txt))
    
    for p in pages:
        if p.stem not in all_links:
            issues.append(f"🏝️ {p.stem} – pagina orfana")
    
    for p in pages:
        txt = p.read_text(encoding='utf-8')
        links = re.findall(r'\[\[([^\]]+)\]\]', txt)
        for link in links:
            if not (BOOK_PAGES / f"{link}.md").exists():
                issues.append(f"🔗 {p.stem} → [[{link}]] (link rotto)")
    
    if issues:
        print(f"\n📋 Trovati {len(issues)} problemi:")
        for i in issues[:15]:
            print(f"   {i}")
        log_activity("LINT", f"Trovati {len(issues)} problemi", None)
    else:
        print("   ✅ Book in perfetta salute!")
        log_activity("LINT", "Nessun problema", None)

def status():
    print("\n" + "="*50)
    print("📚 STATO DEL BOOK")
    print("="*50)
    print(f"📌 clippings/:     {len(list(CLIPPINGS.glob('*.md')))}")
    print(f"🗄️ raw/:          {len(list(RAW.glob('*.md')))}")
    print(f"📖 book/pages/:   {len(list(BOOK_PAGES.glob('*.md')))}")
    print("="*50)

def list_clippings():
    files = list(CLIPPINGS.glob("*.md"))
    if not files:
        print("📭 clippings/ è vuoto")
    else:
        print("\n📌 File in clippings/:")
        for f in files:
            print(f"   • {f.name}")

def list_raw():
    files = list(RAW.glob("*.md"))
    if not files:
        print("📭 raw/ è vuoto")
    else:
        print("\n🗄️ File in raw/:")
        for f in files:
            print(f"   • {f.name}")

def list_books():
    files = list(BOOK_PAGES.glob("*.md"))
    if not files:
        print("📭 book/pages/ è vuoto")
    else:
        print("\n📚 Opere nel book:")
        print("-" * 60)
        for f in sorted(files):
            content = f.read_text(encoding='utf-8')
            title = f.stem
            for line in content.split('\n')[:5]:
                if line.startswith('# '):
                    title = line[2:].strip()
                    break
            work_type = ""
            lang = ""
            for line in content.split('\n')[:15]:
                if 'type:' in line:
                    work_type = line.split(':', 1)[1].strip().strip('"')
                if 'language:' in line:
                    lang = line.split(':', 1)[1].strip().strip('"')
            print(f"   📖 [[{f.stem}]]")
            print(f"      Titolo: {title}")
            print(f"      Tipo: {work_type} | Lingua: {lang}")
            print()

def move_to_raw(filename):
    src = CLIPPINGS / filename
    if not src.exists():
        print(f"❌ {filename} non trovato in clippings/")
        return
    shutil.move(str(src), str(RAW / filename))
    print(f"✅ Spostato {filename} → raw/")

# ==================== MAIN ====================

def main():
    print("\n" + "="*70)
    print("📚 LLM Book Manager")
    print("Classificazione russa: рассказ + повесть → racconto, роман → romanzo")
    print("Convenzioni: underscore per link, entities, tags")
    print("Marker citazioni: >> ... << (multi-riga supportato)")
    print("="*70)
    
    print("\n📖 COMANDI PRINCIPALI:")
    print("  ingest <file> -i                     → crea riassunto (interattivo)")
    print("  ingest <file> -i --capitolo N --opera \"Titolo\" --autore \"Nome\"")
    print("  update <file> --capitolo N --opera \"Titolo\" --autore \"Nome\"")
    print("  complete <opera> --autore \"Nome\"    → riassunto finale romanzo")
    print("  translate <page> <lang>              → traduce una pagina")
    print("  article <page> --format substack    → genera articolo Substack")
    print("  publish <page> --target it --platform substack")
    print("  query <testo>                        → interroga il book")
    print("  quote <page>                         → estrae citazioni")
    print("  compare <page1> <page2>              → confronta due opere")
    print("  timeline <page>                      → timeline eventi")
    print("  character <page>                     → analisi personaggi")
    print("  theme <page>                         → analisi temi")
    print("  lint, status, list, list-raw, list-books, move")
    print("  list-processed, reset-hashes, help, exit")
    print("="*70)
    print("💡 Usa TAB per autocompletare comandi e nomi file")
    print("🔗 Link: [[Nome_Con_Underscore]]")
    print("📌 Citazioni: >> Testo della citazione <<")
    print("="*70)

    setup_autocomplete()

    while True:
        try:
            cmd = input("\n📚 > ").strip()
            if not cmd:
                continue
            parts = cmd.split()
            c = parts[0].lower()

            if c == 'list':
                list_clippings()
            elif c == 'list-raw':
                list_raw()
            elif c == 'list-books':
                list_books()
            elif c == 'move' and len(parts) > 1:
                move_to_raw(parts[1])
            elif c == 'ingest' and len(parts) > 1:
                filename = parts[1]
                force = '--force' in parts
                interactive = '--interactive' in parts or '-i' in parts
                
                capitolo_num = None
                opera_title = None
                opera_author = None
                
                for i, part in enumerate(parts):
                    if part == '--capitolo' and i + 1 < len(parts):
                        capitolo_num = parts[i + 1]
                    if part == '--opera' and i + 1 < len(parts):
                        opera_title = parts[i + 1]
                    if part == '--autore' and i + 1 < len(parts):
                        opera_author = parts[i + 1]
                
                ingest(filename, force, interactive, capitolo_num, opera_title, opera_author)
            elif c == 'update' and len(parts) > 1:
                filename = parts[1]
                force = '--force' in parts
                
                capitolo_num = None
                opera_title = None
                opera_author = None
                
                for i, part in enumerate(parts):
                    if part == '--capitolo' and i + 1 < len(parts):
                        capitolo_num = parts[i + 1]
                    if part == '--opera' and i + 1 < len(parts):
                        opera_title = parts[i + 1]
                    if part == '--autore' and i + 1 < len(parts):
                        opera_author = parts[i + 1]
                
                update_existing(filename, force, capitolo_num, opera_title, opera_author)
            elif c == 'complete' and len(parts) > 1:
                opera_title = parts[1]
                opera_author = None
                for i, part in enumerate(parts):
                    if part == '--autore' and i + 1 < len(parts):
                        opera_author = parts[i + 1]
                complete_summary(opera_title, opera_author)
            elif c == 'extract' and len(parts) > 1:
                filename = parts[1]
                force = '--force' in parts
                extract(filename, force)
            elif c == 'query' and len(parts) > 1:
                query(' '.join(parts[1:]))
            elif c == 'deep' and len(parts) > 1:
                deep_search(' '.join(parts[1:]))
            elif c == 'quote' and len(parts) > 1:
                char = None if len(parts) <= 2 else ' '.join(parts[2:])
                quote(parts[1], char)
            elif c == 'compare' and len(parts) > 2:
                compare(parts[1], parts[2])
            elif c == 'timeline' and len(parts) > 1:
                timeline(parts[1])
            elif c == 'character' and len(parts) > 1:
                char = None if len(parts) <= 2 else ' '.join(parts[2:])
                character(parts[1], char)
            elif c == 'theme' and len(parts) > 1:
                theme(parts[1])
            elif c == 'translate' and len(parts) > 1:
                target = "it" if len(parts) <= 2 else parts[2]
                translate_page(parts[1], target)
            elif c == 'article' and len(parts) > 1:
                page_name = parts[1]
                format = "substack"
                target_lang = "it"
                for i, part in enumerate(parts):
                    if part == '--format' and i + 1 < len(parts):
                        format = parts[i + 1]
                    if part == '--lang' and i + 1 < len(parts):
                        target_lang = parts[i + 1]
                generate_article(page_name, format, target_lang)
            elif c == 'publish' and len(parts) > 1:
                page_name = parts[1]
                target_lang = "it"
                platform = "substack"
                for i, part in enumerate(parts):
                    if part == '--target' and i + 1 < len(parts):
                        target_lang = parts[i + 1]
                    if part == '--platform' and i + 1 < len(parts):
                        platform = parts[i + 1]
                publish(page_name, target_lang, platform)
            elif c == 'lint':
                lint()
            elif c == 'status':
                status()
            elif c == 'list-processed':
                list_processed()
            elif c == 'reset-hashes':
                reset_processed()
            elif c == 'help':
                main()
            elif c == 'exit':
                print("👋 Arrivederci!")
                break
            else:
                print("Comando non riconosciuto. Usa 'help'")
        except KeyboardInterrupt:
            print("\n👋 Arrivederci!")
            break
        except Exception as e:
            print(f"❌ Errore: {e}")

if __name__ == "__main__":
    main()
