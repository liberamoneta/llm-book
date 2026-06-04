# how it works
1. Tu scrivi/modifichi BOOK_AGENTS.md (le regole)
                ↓
2. Io (LLM) leggo BOOK_AGENTS.md
                ↓
3. Io uso quelle regole per scrivere/aggiornare book.py
                ↓
4. book.py contiene il collegamento a DeepSeek API (via .env)
                ↓
5. Tu esegui python3 book.py
                ↓
6. book.py costruisce i prompt seguendo le regole di BOOK_AGENTS.md
                ↓
7. DeepSeek API (LLM) riceve il prompt e genera il riassunto
                ↓
8. Il riassunto segue il formato obbligatorio di BOOK_AGENTS.md


✅ RIEPILOGO DEI COMANDI
Comando	Descrizione
ingest file.md -i	Crea riassunto (interattivo)
ingest file.md -i --capitolo 1 --opera "Titolo" --autore "Nome"	Crea riassunto capitolo
update file.md --capitolo 2 --opera "Titolo" --autore "Nome"	Aggrega capitolo a romanzo
complete "Titolo" --autore "Nome"	Genera riassunto finale del romanzo
translate page it	Traduce in italiano
article page --format substack	Genera articolo Substack
publish page --target it --platform substack	Traduce + genera articolo
ingest file.md -i	Crea riassunto (interattivo)
ingest file.md -i --capitolo 1 --opera "Titolo" --autore "Nome"	Crea riassunto capitolo
update file.md --capitolo 2 --opera "Titolo" --autore "Nome"	Aggrega capitolo a romanzo
complete "Titolo" --autore "Nome"	Genera riassunto finale del romanzo
translate page it	Traduce in italiano
ingest file.md -i	Crea riassunto (interattivo)
ingest file.md -i --capitolo 1 --opera "Titolo" --autore "Nome"	Crea riassunto capitolo
update file.md --capitolo 2 --opera "Titolo" --autore "Nome"	Aggrega capitolo a romanzo
complete "Titolo" --autore "Nome"	Genera riassunto finale del romanzo
translate page it	Traduce in italiano


📚 > ingest Opera.md -i
📚 > translate Opera_racconto it
📚 > article Opera_racconto_it --format substack
📚 > publish Opera_racconto --target it --platform substack

📚 > ingest Capitolo_1.md -i --capitolo 1 --opera "Titolo" --autore "Nome"
📚 > update Capitolo_2.md --capitolo 2 --opera "Titolo" --autore "Nome"
📚 > update Capitolo_3.md --capitolo 3 --opera "Titolo" --autore "Nome"
...
📚 > complete "Titolo" --autore "Nome"
📚 > translate Titolo_riassunto_completo it
📚 > article Titolo_riassunto_completo_it --format substack

📚 > query "domanda su qualsiasi opera o autore"
📚 > quote Opera_racconto
📚 > character Opera_racconto
📚 > theme Opera_racconto
📚 > timeline Opera_racconto
📚 > compare Opera1 Opera2