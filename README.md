# FastAPI Blog

Un blog multiutente con API REST e pagine web, scritto con **FastAPI**. Gli utenti si registrano, accedono, pubblicano post, caricano la foto profilo e possono recuperare la password via email.

Progetto di studio, ispirato al corso FastAPI di Corey Schafer e poi esteso con migrazioni, test automatici e il flusso di reset password.

## Funzionalità

- **Autenticazione** con token JWT e password salvate con hashing Argon2.
- **Reset password via email**: il token viene salvato solo come hash SHA-256, ha una scadenza e la richiesta risponde sempre allo stesso modo, per non rivelare quali email sono registrate.
- **Post**: creazione, modifica, cancellazione e lista paginata. Solo l'autore può modificare o cancellare i propri post.
- **Profilo utente**: modifica dei dati e foto profilo, ritagliata a 300x300 e salvata su S3.
- **Pagine web** renderizzate con Jinja2 (home, post, profilo, login, registrazione) e documentazione OpenAPI generata in automatico su `/docs`.
- **Endpoint `/health`** che verifica anche la connessione al database.

## Stack

| Area         | Strumenti                                     |
| ------------ | --------------------------------------------- |
| Backend      | FastAPI, Pydantic, pydantic-settings          |
| Database     | PostgreSQL, SQLAlchemy 2 (asincrono), Alembic |
| Sicurezza    | PyJWT, pwdlib (Argon2)                        |
| File e email | boto3 (S3), Pillow, aiosmtplib                |
| Frontend     | Jinja2, Bootstrap, JavaScript                 |
| Test         | pytest, moto (S3 simulato)                    |
| Pacchetti    | uv                                            |

## Avvio in locale

**Requisiti:** Python 3.14, [uv](https://docs.astral.sh/uv/), un database PostgreSQL e un bucket S3 (o un servizio compatibile, impostando `S3_ENDPOINT_URL`).

1. Clona il repository e installa le dipendenze:

   ```bash
   git clone https://github.com/alessiotegoni/fastapi-corey-vps.git
   cd fastapi-corey-vps
   uv sync
   ```

2. Crea un file `.env` nella root. Le variabili obbligatorie sono tre, le altre hanno un valore di default (vedi [config.py](config.py)):

   ```env
   DATABASE_URL=postgresql+psycopg://utente:password@localhost/blog
   SECRET_KEY=<stringa casuale>
   S3_BUCKET_NAME=<nome del bucket>
   ```

   Per generare `SECRET_KEY`:

   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

3. Applica le migrazioni e avvia il server:

   ```bash
   uv run alembic upgrade head
   uv run fastapi dev
   ```

L'app è su <http://localhost:8000> e la documentazione delle API su <http://localhost:8000/docs>.

Per riempire il database con utenti e post di esempio:

```bash
uv run python -m scripts.populate_db
```

## Test

I test usano l'app vera, un database PostgreSQL dedicato che si azzera a ogni test e un S3 simulato con moto.

> [!NOTE]
> Il database `test_blog` va creato a mano (`CREATE DATABASE test_blog;`). A fine run le sue tabelle vengono cancellate, quindi non puntarlo a un database con dati veri.

Metti l'URL in un file `.env.test` nella root:

```env
TEST_DATABASE_URL=postgresql+psycopg://utente:password@localhost/test_blog
```

```bash
uv run pytest tests/ -v
```

## Struttura

```text
main.py        app FastAPI, pagine web e gestione degli errori
config.py      variabili d'ambiente tipizzate
database.py    engine e sessione asincroni
models.py      modelli SQLAlchemy (User, Post, PasswordResetToken)
routers/       endpoint API: auth, users, posts
schemas/       modelli Pydantic di richiesta e risposta
utils/         JWT e hashing, immagini e S3, invio email
alembic/       migrazioni del database
templates/     pagine Jinja2
tests/         test automatici
scripts/       popolamento del database e verifica delle credenziali S3
```
