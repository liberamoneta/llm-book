#!/usr/bin/env python3
"""
LLM Book Manager - Dedicato a opere narrative
Supporto: teatro, romanzi, poesia, racconti, saggi letterari
Lingue: italiano, russo, inglese (rilevamento automatico)
Convenzioni: underscore per entities, tags, links, titoli

Marker citazioni: >> all'inizio riga
Esempio:
    >> Testo della citazione
    >> Testo della citazione — Personaggio

Comandi:
  ingest, update, extract, query, deep, quote, compare, timeline,
  character, theme, scene, translate, lint, status, list, list-raw,
  list-books, move, reset-hashes, list-processed, help, exit
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
    'character', 'theme', 'scene', 'translate', 'lint', 'status',
    'list-processed', 'reset-hashes', 'help', 'exit'
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

for d in [CLIPPINGS, RAW, RAW_ASSETS, BOOK, BOOK_PAGES]:
    d.mkdir(exist_ok=True)

# ==================== FUNZIONI AUTOCOMPLETAMENTO ====================

def get_raw_files(text=""):
    try:
        files = [f.name for f in RAW.glob(f"{text}*.md") if f.is_file()]
        return sorted(files)
    except:
        return []

def get_book_pages(text=""):
    try:
        files = [f.stem for f in BOOK_PAGES.glob(f"{text}*.md") if f.is_file()]
        return sorted(files)
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
        elif cmd in ['query', 'quote', 'compare', 'timeline', 'character', 'theme', 'scene', 'translate']:
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
    hash_db = load_hash_db()
    return hash_db.get(filename)

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

# ==================== NORMALIZZAZIONE ====================

def normalize_spaces(text):
    """Converte spazi in underscore e rimuove caratteri non validi"""
    if not text:
        return text
    text = text.replace(' ', '_').replace('-', '_')
    text = re.sub(r'[^\w\u0400-\u04FF\-_.]', '', text)
    return text

def normalize_links(content):
    """Converte gli spazi nei link [[...]] in underscore"""
    def replace_link(match):
        link_text = match.group(1)
        normalized = normalize_spaces(link_text)
        return f'[[{normalized}]]'
    return re.sub(r'\[\[([^\]]+)\]\]', replace_link, content)

# ==================== FUNZIONI UTILI ====================

def extract_highlighted_quotes(content):
    """
    Estrae le citazioni evidenziate con marker >> all'inizio riga.
    Formato: >> Testo della citazione
    Restituisce: (lista_citazioni, contenuto_pulito)
    """
    quotes = []
    lines = content.split('\n')
    clean_lines = []
    
    for line in lines:
        if re.match(r'^>>\s+', line):
            quote = re.sub(r'^>>\s+', '', line).strip()
            if quote:
                quotes.append(quote)
        else:
            clean_lines.append(line)
    
    clean_content = '\n'.join(clean_lines)
    return quotes, clean_content

def detect_language(text):
    text_sample = text[:1000]
    has_cyrillic = any(ord(c) > 0x0400 for c in text_sample)
    has_italian_accents = any(c in 'àèéìòù' for c in text_sample.lower())
    
    if has_cyrillic:
        return "ru"
    elif has_italian_accents:
        return "it"
    else:
        return "en"

def detect_work_type(content):
    """Rileva il tipo di opera: theater, novel, poetry, short_story, essay"""
    content_lower = content.lower()
    
    theater_signals = ['явление', 'действие', 'акт', 'сцена', 'реплика',
                       'dialogue', 'act', 'scene', 'enter', 'exit',
                       'personaggio', 'attore', 'copione']
    for signal in theater_signals:
        if signal in content_lower:
            return "theater"
    
    poetry_signals = ['стих', 'рифм', 'строф', 'poem', 'verse', 'rhyme',
                      'stanza', 'metrica', 'sonetto']
    for signal in poetry_signals:
        if signal in content_lower:
            return "poetry"
    
    if len(content) > 15000:
        return "novel"
    
    if len(content) < 8000:
        return "short_story"
    
    essay_signals = ['analisi', 'critica', 'interpretazione', 'contesto storico']
    if any(s in content_lower for s in essay_signals):
        return "essay"
    
    return "novel"

def detect_author_from_content(content, lang):
    """Tenta di estrarre il nome dell'autore dal testo"""
    author_patterns = {
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
    
    for pattern in author_patterns.get(lang, []):
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
    """Aggiorna l'indice del book"""
    pages = list(BOOK_PAGES.glob("*.md"))
    
    index = f"""# 📚 Indice del Book

Ultimo aggiornamento: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Statistiche
- Opere totali: {len(pages)}
- Fonti in raw: {len(list(RAW.glob('*.md')))}

## Opere per tipo

"""
    by_type = {"theater": [], "novel": [], "poetry": [], "short_story": [], "essay": [], "other": []}
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
        "theater": "🎭 Teatro",
        "novel": "📖 Romanzi",
        "poetry": "📜 Poesia",
        "short_story": "📝 Racconti",
        "essay": "✍️ Saggi",
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

def get_language_instructions(lang):
    if lang == "ru":
        return "Mantieni il testo in RUSSO. НЕ переводи."
    elif lang == "it":
        return "Mantieni il testo in ITALIANO. NON tradurre."
    else:
        return "Mantieni il testo in ENGLISH. DO NOT translate."

# ==================== PROMPT COSTRUTTORI ====================

def build_ingest_prompt(content, title, author, lang, work_type, highlighted_quotes=None):
    """Costruisce il prompt per l'ingest"""
    lang_name = {"ru": "russo", "it": "italiano", "en": "inglese"}.get(lang, "originale")
    
    quotes_section = ""
    if highlighted_quotes:
        quotes_section = "\n\n## 📌 CITAZIONI EVIDENZIATE DALL'UTENTE\n\n"
        quotes_section += "Queste citazioni DEVONO apparire nella sezione '💬 Battute celebri'.\n\n"
        for q in highlighted_quotes:
            quotes_section += f"- {q}\n"
        quotes_section += "\n"
    
    if work_type == "theater":
        return f"""Sei un drammaturgo. Riassumi fedelmente quest'opera teatrale.

TESTO:
{content[:8000]}

AUTORE: {author}
TITOLO: {title}
LINGUA: {lang_name}
{quotes_section}
STRUTTURA:

# {title}

> *[Citazione più significativa]*

## 📜 Scheda
| Campo | Dettaglio |
|-------|-----------|
| **Autore** | {author} |
| **Tipo** | Opera teatrale |
| **Lingua** | {lang_name} |

## 🎭 Personaggi
[Lista completa: nome, ruolo, descrizione]

## 📖 Riassunto per atti

### Atto I
[Eventi, dialoghi chiave]

### Atto II
...

## 💬 Battute celebri
[Lista delle citazioni, PRIORITARIE quelle evidenziate]

## 🎯 Temi principali
[2-3 temi]

## 🔗 Collegamenti
- [[personaggio]]

⚠️ Mantieni la lingua {lang_name}. Citazioni LETTERALI. USA underscore nei link."""

    elif work_type == "poetry":
        return f"""Sei un poeta. Analizza fedelmente questa poesia.

TESTO:
{content[:4000]}

AUTORE: {author}
TITOLO: {title}
LINGUA: {lang_name}
{quotes_section}
STRUTTURA:

# {title}

> *[Primo verso]*

## 📜 Scheda
| Campo | Dettaglio |
|-------|-----------|
| **Autore** | {author} |
| **Tipo** | Poesia |
| **Lingua** | {lang_name} |

## 📝 Testo originale
```poem
[Inserisci qui il testo completo della poesia, esattamente come fornito, riga per riga, senza modifiche]
```

## 🎨 Figure retoriche
[Elenca le figure retoriche presenti: metafore, similitudini, enjambement, rime, allitterazioni, personificazioni, ossimori, ecc. NON alterare il testo originale]

## 💭 Significato complessivo
[Interpretazione generale in 2-3 frasi. NON fare la parafrasi verso per verso.]

## 🔗 Collegamenti
- [[poesia]]
- [[autore]]

⚠️ Mantieni la lingua {lang_name}.
⚠️ NON fare la parafrasi verso per verso.
⚠️ NON alterare il testo originale della poesia.
⚠️ La sezione "Testo originale" deve contenere la poesia esattamente come fornita dall'utente."""

    else:
        return f"""Sei un lettore attento. Riassumi fedelmente quest'opera.

TESTO:
{content[:8000]}

AUTORE: {author}
TITOLO: {title}
TIPO: {work_type}
LINGUA: {lang_name}
{quotes_section}
STRUTTURA:

# {title}

> *[Citazione significativa]*

## 📜 Scheda
| Campo | Dettaglio |
|-------|-----------|
| **Autore** | {author} |
| **Tipo** | {work_type} |
| **Lingua** | {lang_name} |

## 👥 Personaggi principali
[Lista con descrizioni]

## 📖 Riassunto
[Sequenza cronologica della trama]

## 💬 Citazioni
[Lista delle citazioni, PRIORITARIE quelle evidenziate]

## 🎯 Temi
[Temi principali]

## 🔗 Collegamenti
- [[personaggio]]

Mantieni la lingua {lang_name}. Sii fedele al testo."""

# ==================== COMANDI PRINCIPALI ====================

def ingest(filename, force=False):
    """Crea riassunto per opera narrativa"""
    src = RAW / filename
    if not src.exists():
        print(f"❌ {filename} non trovato in raw/")
        return

    if not force:
        if is_file_processed(filename, "ingest"):
            file_info = get_file_info(filename)
            print(f"\n⏭️ SKIP: {filename} già elaborato (hash invariato)")
            if file_info and file_info.get("page"):
                print(f"   Pagina esistente: [[{file_info['page']}]]")
            print("   Usa 'ingest --force' per forzare la rielaborazione")
            return
    else:
        print("   ⚡ Forzatura: rielaborazione anche se già processato")

    print(f"\n📚 INGEST: {filename}")
    content = src.read_text(encoding='utf-8')
    
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            content = parts[2].strip()
    
    highlighted_quotes, clean_content = extract_highlighted_quotes(content)
    
    if highlighted_quotes:
        print(f"   📌 Estratte {len(highlighted_quotes)} citazioni evidenziate (>>)")
    
    work_type = detect_work_type(clean_content)
    lang = detect_language(clean_content)
    author = detect_author_from_content(clean_content, lang)
    
    title = filename.replace('.md', '')
    for line in clean_content.split('\n')[:10]:
        if line.startswith('# '):
            title = line[2:].strip()
            break
    
    safe_title = normalize_spaces(title)
    if len(safe_title) > 50:
        safe_title = safe_title[:50]
    
    print(f"   🎭 Tipo rilevato: {work_type}")
    print(f"   🌐 Lingua: {lang}")
    print(f"   ✍️ Autore: {author}")
    
    prompt = build_ingest_prompt(clean_content, title, author, lang, work_type, highlighted_quotes)
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    
    summary_content = response.choices[0].message.content
    summary_content = normalize_links(summary_content)
    
    page_name = f"{safe_title}_{work_type}"
    page_path = BOOK_PAGES / f"{page_name}.md"
    
    counter = 1
    while page_path.exists():
        page_name = f"{safe_title}_{work_type}_{counter}"
        page_path = BOOK_PAGES / f"{page_name}.md"
        counter += 1
    
    entities = re.findall(r'\[\[([^\]]+)\]\]', summary_content)
    entities = [normalize_spaces(e) for e in set(entities)]
    entities = list(set(entities))[:8]
    entities_str = json.dumps(entities, ensure_ascii=False) if entities else "[]"
    
    tags = [work_type, "riassunto"]
    if lang == "ru":
        tags.append("russian")
    elif lang == "it":
        tags.append("italian")
    else:
        tags.append("english")
    
    tags = [normalize_spaces(t) for t in set(tags)]
    tags = list(set(tags))[:6]
    tags_str = json.dumps(tags, ensure_ascii=False)
    
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
---

"""
    page_path.write_text(frontmatter + summary_content, encoding='utf-8')
    
    mark_file_processed(filename, page_name, "ingest")
    
    print(f"   ✅ Riassunto creato: book/pages/{page_name}.md")
    print(f"   📊 Parole: {word_count}")
    print(f"   🏷️ Tags: {len(tags)}")
    print(f"   🔗 Entities: {len(entities)}")
    if highlighted_quotes:
        print(f"   💬 Citazioni evidenziate: {len(highlighted_quotes)}")
    
    log_activity("INGEST", f"Creato riassunto da {filename} (tipo: {work_type})", filename)
    update_index()
    
    return page_name

def update_existing(filename, force=False):
    """Aggiorna una pagina esistente con nuove informazioni"""
    src = RAW / filename
    if not src.exists():
        print(f"❌ {filename} non trovato in raw/")
        return

    if not force:
        if is_file_processed(filename, "update"):
            file_info = get_file_info(filename)
            print(f"\n⏭️ SKIP UPDATE: {filename} già usato")
            print("   Usa 'update --force' per forzare")
            return
    else:
        print("   ⚡ Forzatura: update anche se già processato")

    print(f"\n🔄 UPDATE: {filename}")
    content = src.read_text(encoding='utf-8')
    
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            content = parts[2].strip()
    
    highlighted_quotes, clean_content = extract_highlighted_quotes(content)
    
    if highlighted_quotes:
        print(f"   📌 Estratte {len(highlighted_quotes)} citazioni evidenziate (>>)")
    
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
            old_frontmatter = parts[1]
            old_body = parts[2].strip()
            for line in old_frontmatter.split('\n'):
                if line.startswith('language:'):
                    old_lang = line.split(':', 1)[1].strip().strip('"').strip("'")
                if line.startswith('title:'):
                    old_title = line.split(':', 1)[1].strip().strip('"')
    
    lang_instruction = get_language_instructions(old_lang)
    
    quotes_note = ""
    if highlighted_quotes:
        quotes_note = f"\n\nNUOVE CITAZIONI DA AGGIUNGERE:\n" + "\n".join([f"- {q}" for q in highlighted_quotes])
    
    merge_prompt = f"""Fondi queste due versioni.

PAGINA ESISTENTE:
{old_body[:3000]}

NUOVA FONTE:
{clean_content[:3000]}
{quotes_note}

{lang_instruction}

1. Mantieni info da entrambe
2. Risolvi contraddizioni (privilegia nuova fonte)
3. AGGIUNGI le nuove citazioni alla sezione "💬 Battute celebri"
4. Mantieni la lingua della pagina esistente

Restituisci SOLO il contenuto aggiornato."""
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": merge_prompt}],
        temperature=0.3
    )
    
    merged_content = response.choices[0].message.content
    merged_content = normalize_links(merged_content)
    
    entities = re.findall(r'\[\[([^\]]+)\]\]', merged_content)
    entities = [normalize_spaces(e) for e in set(entities)]
    entities = list(set(entities))[:8]
    entities_str = json.dumps(entities, ensure_ascii=False) if entities else "[]"
    
    tags = ["aggiornato"]
    if old_lang == "ru":
        tags.append("russian")
    elif old_lang == "it":
        tags.append("italian")
    tags = [normalize_spaces(t) for t in set(tags)]
    tags_str = json.dumps(tags, ensure_ascii=False)
    
    new_frontmatter = f"""---
title: "{old_title}"
type: {detect_work_type(merged_content)}
language: {old_lang}
author: "{detect_author_from_content(merged_content, old_lang)}"
source: [{filename}]
created: {datetime.now().date()}
updated: {datetime.now().date()}
word_count: {len(merged_content.split())}
tags: {tags_str}
entities: {entities_str}
status: "aggiornato"
---

"""
    
    target_page.write_text(new_frontmatter + merged_content, encoding='utf-8')
    
    mark_file_processed(filename, target_name, "update")
    
    print(f"   ✅ Pagina aggiornata: {target_name}")
    print(f"   🔗 Entities: {len(entities)}")
    if highlighted_quotes:
        print(f"   💬 Aggiunte {len(highlighted_quotes)} citazioni")
    
    log_activity("UPDATE", f"Aggiornata [[{target_name}]] con {filename}", filename)
    update_index()

def extract(filename, force=False):
    """Crea versione essenziale (solo punti chiave)"""
    src = RAW / filename
    if not src.exists():
        print(f"❌ {filename} non trovato in raw/")
        return

    if not force:
        if is_file_processed(filename, "extract"):
            print(f"\n⏭️ SKIP EXTRACT: {filename} già elaborato")
            print("   Usa 'extract --force' per forzare")
            return
    else:
        print("   ⚡ Forzatura: extract anche se già processato")

    print(f"\n📌 EXTRACT: {filename}")
    content = src.read_text(encoding='utf-8')
    
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            content = parts[2].strip()
    
    highlighted_quotes, clean_content = extract_highlighted_quotes(content)
    
    if highlighted_quotes:
        print(f"   📌 Estratte {len(highlighted_quotes)} citazioni evidenziate")
    
    title = filename.replace('.md', '')
    for line in clean_content.split('\n'):
        if line.startswith('# '):
            title = line[2:].strip()
            break
    
    work_type = detect_work_type(clean_content)
    lang = detect_language(clean_content)
    
    quotes_text = ""
    if highlighted_quotes:
        quotes_text = "\n\nCitazioni evidenziate:\n" + "\n".join([f"- {q}" for q in highlighted_quotes])
    
    prompt = f"""Estrai SOLO l'essenziale da quest'opera {work_type}.

TESTO:
{clean_content[:5000]}
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
(USA UNA DELLE CITAZIONI EVIDENZIATE se disponibili)

Sii ultra-conciso. Nessuna analisi."""
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    
    wiki_content = response.choices[0].message.content
    wiki_content = normalize_links(wiki_content)
    
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
    page_path.write_text(frontmatter + wiki_content, encoding='utf-8')
    
    mark_file_processed(filename, page_name, "extract")
    
    print(f"   ✅ Versione essenziale: book/pages/{page_name}.md")
    log_activity("EXTRACT", f"Creato essenziale da {filename}", filename)
    update_index()
    
    return page_name

def query(question):
    """Interroga il book"""
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
        context += f"\n## [[{p.stem}]]\n{txt[:1500]}\n"
    
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
    """Cerca informazioni in rete"""
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
    print("="*60)
    print(response.choices[0].message.content)
    print("="*60)
    log_activity("DEEP_SEARCH", f"Ricerca web: {question[:100]}", None)

def quote(page_name, character=None):
    """Estrae citazioni da un'opera"""
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
{content[:4000]}

{"Personaggio specifico: " + character if character else ""}

Restituisci in formato markdown:
- Citazione — Personaggio (atto/scena/capitolo)
- ..."""
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    
    print("\n" + "="*60)
    print(f"💬 CITAZIONI DA {page_name}")
    print("="*60)
    print(response.choices[0].message.content)
    print("="*60)

def compare(work1, work2):
    """Confronta due opere"""
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
{content1[:3000]}

OPERA 2: {work2}
{content2[:3000]}

STRUTTURA:
- Temi comuni
- Differenze principali
- Personaggi (se applicabile)
- Stile narrativo
- Conclusione"""
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    
    print("\n" + "="*60)
    print(f"📖 CONFRONTO: {work1} vs {work2}")
    print("="*60)
    print(response.choices[0].message.content)
    print("="*60)

def timeline(page_name):
    """Estrae la timeline degli eventi"""
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
{content[:5000]}

Restituisci in formato:
## Timeline
1. [Evento 1] - [Atto/Scena/Capitolo]
2. [Evento 2] - ...
...
"""
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    
    print("\n" + "="*60)
    print(f"📅 TIMELINE: {page_name}")
    print("="*60)
    print(response.choices[0].message.content)
    print("="*60)

def character(page_name, char_name=None):
    """Analizza i personaggi di un'opera"""
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
{content[:5000]}

{"Personaggio specifico: " + char_name if char_name else "Elenco tutti i personaggi"}

Restituisci per ogni personaggio:
- Nome
- Ruolo
- Caratteristiche
- Evoluzione (se presente)"""
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    
    print("\n" + "="*60)
    print(f"🎭 PERSONAGGI: {page_name}")
    print("="*60)
    print(response.choices[0].message.content)
    print("="*60)

def theme(page_name):
    """Analizza i temi di un'opera"""
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
{content[:5000]}

Per ogni tema:
- Nome del tema
- Come si manifesta
- Esempi dal testo
- Significato"""
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    
    print("\n" + "="*60)
    print(f"🎯 TEMI: {page_name}")
    print("="*60)
    print(response.choices[0].message.content)
    print("="*60)

def scene(page_name, act=None, scene_num=None):
    """Analizza una scena specifica (per teatro)"""
    page_path = BOOK_PAGES / f"{page_name}.md"
    if not page_path.exists():
        print(f"❌ Pagina {page_name} non trovata")
        return
    
    content = page_path.read_text(encoding='utf-8')
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            content = parts[2].strip()
    
    scene_spec = ""
    if act:
        scene_spec = f"Atto {act}"
        if scene_num:
            scene_spec += f", Scena {scene_num}"
    
    prompt = f"""Analizza questa scena dell'opera.

OPERA:
{content[:5000]}

SCENA: {scene_spec if scene_spec else "Tutte le scene"}

Restituisci:
- Personaggi presenti
- Eventi principali
- Dialoghi chiave
- Funzione nella trama"""
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    
    print("\n" + "="*60)
    print(f"🎬 SCENA: {page_name} {scene_spec}")
    print("="*60)
    print(response.choices[0].message.content)
    print("="*60)

def translate_page(page_name, target_lang="it"):
    """Traduce una pagina in un'altra lingua"""
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
            frontmatter = parts[1]
            body = parts[2].strip()
            for line in frontmatter.split('\n'):
                if line.startswith('language:'):
                    original_lang = line.split(':', 1)[1].strip().strip('"').strip("'")
                    break
    
    lang_map = {'it': 'italiano', 'ru': 'russo', 'en': 'inglese'}
    
    prompt = f"""Traduci quest'opera in {lang_map[target_lang]}.

TESTO ORIGINALE ({lang_map[original_lang]}):
{body[:6000]}

Mantieni la struttura markdown e i link [[...]].
Traduci i titoli delle sezioni.
Restituisci SOLO il testo tradotto."""
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    
    translated_body = response.choices[0].message.content
    
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
    translated_path.write_text(frontmatter + translated_body, encoding='utf-8')
    
    print(f"   ✅ Traduzione creata: book/pages/{translated_name}.md")
    log_activity("TRANSLATE", f"Tradotta [[{page_name}]] in {target_lang}", None)
    update_index()

def lint():
    """Controlla la salute del book"""
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
    """Mostra statistiche"""
    clips = len(list(CLIPPINGS.glob("*.md")))
    raws = len(list(RAW.glob("*.md")))
    books = len(list(BOOK_PAGES.glob("*.md")))
    
    print("\n" + "="*50)
    print("📚 STATO DEL BOOK")
    print("="*50)
    print(f"📌 clippings/:     {clips}")
    print(f"🗄️ raw/:          {raws}")
    print(f"📖 book/pages/:   {books}")
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
    print("Dedicato a opere narrative: teatro, romanzi, poesia, racconti")
    print("Convenzioni: underscore per link, entities, tags")
    print("Marker citazioni: >> all'inizio riga")
    print("="*70)
    
    print("\n📖 COMANDI PRINCIPALI:")
    print("  ingest <file>              → crea riassunto dell'opera")
    print("  ingest <file> --force      → forza la rielaborazione")
    print("  update <file>              → aggiorna opera esistente")
    print("  extract <file>             → versione essenziale (punti chiave)")
    print("  query <testo>              → interroga il book")
    print("  deep <testo>               → cerca in rete")
    print()
    print("🔍 COMANDI ANALITICI:")
    print("  quote <page> [personaggio] → estrae citazioni")
    print("  compare <page1> <page2>    → confronta due opere")
    print("  timeline <page>            → timeline degli eventi")
    print("  character <page> [nome]    → analisi personaggi")
    print("  theme <page>               → analisi temi")
    print("  scene <page> [atto] [scena] → analisi scena")
    print("  translate <page> [lang]    → traduci (it/ru/en)")
    print()
    print("📁 GESTIONE FILE:")
    print("  list, list-raw, list-books, move")
    print("  lint, status")
    print("  list-processed, reset-hashes")
    print("  help, exit")
    print("="*70)
    print("💡 Usa TAB per autocompletare comandi e nomi file")
    print("🔗 Link: [[Nome_Con_Underscore]] non [[Nome Con Spazi]]")
    print("📌 Citazioni: >> Testo della citazione (su riga separata)")
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
                force = len(parts) > 2 and parts[2] == '--force'
                ingest(filename, force)
            elif c == 'update' and len(parts) > 1:
                filename = parts[1]
                force = len(parts) > 2 and parts[2] == '--force'
                update_existing(filename, force)
            elif c == 'extract' and len(parts) > 1:
                filename = parts[1]
                force = len(parts) > 2 and parts[2] == '--force'
                extract(filename, force)
            elif c == 'query' and len(parts) > 1:
                query(' '.join(parts[1:]))
            elif c == 'deep' and len(parts) > 1:
                deep_search(' '.join(parts[1:]))
            elif c == 'quote' and len(parts) > 1:
                char = None
                if len(parts) > 2:
                    char = ' '.join(parts[2:])
                quote(parts[1], char)
            elif c == 'compare' and len(parts) > 2:
                compare(parts[1], parts[2])
            elif c == 'timeline' and len(parts) > 1:
                timeline(parts[1])
            elif c == 'character' and len(parts) > 1:
                char_name = None
                if len(parts) > 2:
                    char_name = ' '.join(parts[2:])
                character(parts[1], char_name)
            elif c == 'theme' and len(parts) > 1:
                theme(parts[1])
            elif c == 'scene' and len(parts) > 1:
                act = None
                scene_num = None
                if len(parts) > 2:
                    act = parts[2]
                if len(parts) > 3:
                    scene_num = parts[3]
                scene(parts[1], act, scene_num)
            elif c == 'translate' and len(parts) > 1:
                target = "it"
                if len(parts) > 2:
                    target = parts[2]
                translate_page(parts[1], target)
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
