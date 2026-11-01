# =============================================================================
# conftest.py: preparazione condivisa da tutti i test della cartella tests/
# =============================================================================
#
# In breve: i test usano l'app vera, ma con un database di prova che si azzera
# dopo ogni test e con un finto S3 in memoria al posto di quello di AWS.
#
# pytest carica questo file da solo prima di eseguire i test (nessun test lo
# importa) e le fixture definite qui sono visibili a tutti i file test_*.py.
#
# FIXTURE
# Una fixture e' una funzione che prepara qualcosa per un test e, se ha uno
# `yield`, lo smonta dopo: il codice prima dello yield e' il setup, quello dopo
# e' il teardown (la pulizia). Il test la richiede scrivendo il suo nome come
# parametro e pytest gli passa il valore prodotto:
#
#   @pytest.mark.anyio
#   async def test_login_returns_token(client):   # "client" e' una fixture
#       await create_test_user(client)
#       token = await login_user(client)
#       assert token
#
# Lo `scope` dice ogni quanto la fixture viene ricreata:
#   - scope="session": una volta per tutta la run (cose costose e condivisibili)
#   - nessuno scope:   prima di ogni singolo test (cose che devono ripartire pulite)
#
# Le fixture si richiedono a catena. Quando un test chiede `client`, pytest
# costruisce questo albero e al termine del test fa il teardown in ordine inverso:
#
#   client
#     +-- db_session
#     |     +-- test_engine        (session)
#     |     +-- setup_database     (session)
#     +-- mocked_aws
#
# PRECONDIZIONI
#   1. Il database `test_blog` deve esistere gia' (CREATE DATABASE test_blog;):
#      questo file crea e cancella le tabelle, non il database.
#   2. L'URL del database di test va in TEST_DATABASE_URL, come variabile
#      d'ambiente oppure nel file .env.test nella root del progetto (escluso da
#      git dal pattern `.env*`). Formato:
#      postgresql+psycopg://utente:password@host/test_blog
#      Deve puntare a un database dedicato ai test: a fine run vengono
#      cancellate tutte le tabelle (setup_database).

# COMANDI
# -v Permette di vedere piu dettagli in console
# -s Permette di vedere i print per ogni test senza che essi falliscano
# uv run pytest tests/ -v (testa tutti i moduli)
# uv run pytest tests/test_users.py -v (testa un solo modulo)
# uv run pytest tests/test_users.py::test_forgot_password_sends_email -v (testa una sola funzione di un modulo)

import asyncio
import os
from collections.abc import AsyncGenerator
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# --- Configurazione di test ---------------------------------------------------
# config.py costruisce `settings = Settings()` nel momento in cui viene
# importato, e pydantic-settings assegna la precedenza alle variabili d'ambiente
# reali sul file .env. Impostarle qui, PRIMA degli import dell'app, fa usare ai
# test la configurazione di test invece di quella di sviluppo (.env).
# Per questo gli import dell'app stanno piu' in basso, di proposito.


# Come config.py con .env, pydantic-settings legge TEST_DATABASE_URL dalle
# variabili d'ambiente e, se manca, dal file .env.test nella root del progetto
# (percorso calcolato da questo file, quindi indipendente dalla cartella da cui
# si lancia pytest). La password del database non e' scritta nel codice.
# `extra="ignore"` permette di aggiungere altre chiavi a .env.test senza errori.
class ConfTestSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / ".env.test",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    test_database_url: str


conftest_settings = ConfTestSettings()  # type: ignore[call-arg]


os.environ["DATABASE_URL"] = conftest_settings.test_database_url
os.environ["S3_BUCKET_NAME"] = "test-bucket"
os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only"

## Dummy S3/AWS Credentials
# Credenziali finte, volutamente. boto3 pretende delle credenziali per firmare
# le richieste, anche se il finto S3 di moto non le controlla. Se per un errore
# il mock non fosse attivo, la chiamata verso l'AWS vero fallirebbe invece di
# scrivere sul bucket reale.
# Le S3_* sono lette da config.py e passate esplicitamente a boto3 in
# utils/images.py; le AWS_* sono quelle che boto3 cerca da solo.
os.environ["S3_ACCESS_KEY_ID"] = "testing"
os.environ["S3_SECRET_ACCESS_KEY"] = "testing"
os.environ["S3_REGION"] = "eu-north-1"

os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_DEFAULT_REGION"] = "eu-north-1"


## App Imports
# Importati dopo le variabili d'ambiente (vedi sopra).
#   - boto3: SDK AWS, qui serve per creare il bucket nel finto S3
#   - pytest: il framework di test (serve per il decoratore @pytest.fixture)
#   - httpx AsyncClient + ASGITransport: client HTTP che chiama l'app in memoria
#   - moto.mock_aws: finto AWS che intercetta le chiamate di boto3
#   - sqlalchemy (async): engine, sessioni e pool di connessioni al database
#   - NullPool: nessun pool, ogni connessione viene aperta e chiusa al bisogno
#   - Base, get_db: i models e la dependency che fornisce la sessione alle route
#   - app: l'applicazione FastAPI da testare
import boto3
import pytest
from httpx import ASGITransport, AsyncClient
from moto import mock_aws
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from database import Base, get_db
from main import app

# Registra il plugin anyio, che permette di eseguire test e fixture
# `async def` (ogni test async richiede anche @pytest.mark.anyio).
# pytest registra gia' questo plugin in automatico tramite entry point.
pytest_plugins = ["anyio"]


## Async backend
# Dice ad anyio quale motore async usare per i test: asyncio, con
# SelectorEventLoop come event loop (il "motore" che esegue le coroutine).
# Su Windows l'event loop predefinito e' ProactorEventLoop, che psycopg non
# supporta in modalita' async (InterfaceError al primo accesso al database);
# SelectorEventLoop e' compatibile e su Linux/macOS e' gia' quello predefinito.
# Ha scope session perche' le fixture async con scope session (come
# setup_database) richiedono un backend con scope almeno uguale.
@pytest.fixture(scope="session")
def anyio_backend():
    return ("asyncio", {"loop_factory": asyncio.SelectorEventLoop})


## Test Engine
# Connessione al database di test (test_blog), creata una volta per tutta la run.
# NullPool non tiene connessioni aperte nel pool: ogni connessione nasce e muore
# dentro il test che la usa, quindi non resta legata a un event loop diverso.
@pytest.fixture(scope="session")
def test_engine():
    return create_async_engine(
        os.environ["DATABASE_URL"],
        poolclass=NullPool,
    )


## Setup Database
# Crea tutte le tabelle dei models (Base.metadata) all'inizio della run e le
# cancella alla fine. Le tabelle nascono da `create_all`, non dalle migrazioni
# Alembic. `run_sync` serve perche' create_all/drop_all sono funzioni sincrone
# di SQLAlchemy, che qui vengono eseguite sopra la connessione async.
@pytest.fixture(scope="session")
async def setup_database(test_engine):
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await test_engine.dispose()


## DB Session (Transactional Rollback)
# Fornisce a ogni test una sessione su un database che a fine test torna vuoto.
#
# Apre una transazione esterna che non viene mai confermata:
#
#   connessione: BEGIN ---------------------------------- ROLLBACK
#                  |                                         |
#                  +-- test: POST /api/users                 |
#                  |     INSERT + db.commit()                |
#                  |     (rilascia solo un SAVEPOINT)        |
#                  +-- test: assert ...                      |
#                                            tabelle di nuovo vuote
#
# join_transaction_mode="create_savepoint" fa agganciare la sessione alla
# transazione esterna: ogni `commit()` fatto dal codice dell'app (i router)
# chiude soltanto un savepoint (un segnalibro dentro la transazione). L'app si
# comporta come in produzione, ma il rollback finale annulla tutto, cosi' ogni
# test parte con le tabelle vuote e non vede i dati degli altri.
# expire_on_commit=False evita che gli oggetti vengano invalidati dopo il commit.
@pytest.fixture
async def db_session(
    test_engine,
    setup_database,
) -> AsyncGenerator[AsyncSession]:
    conn = await test_engine.connect()
    trans = await conn.begin()

    test_async_session = async_sessionmaker(
        bind=conn,
        class_=AsyncSession,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    async with test_async_session() as session:
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()
            await conn.close()


## Mocked AWS
# Un mock e' una versione finta di un servizio esterno, usata solo nei test:
# un test non deve caricare foto sul vero S3 (costa, richiede internet, lascia
# file sporchi).
#
# `mock_aws()` (libreria moto) intercetta le chiamate HTTP di boto3 e le fa
# rispondere a un S3 finto in memoria: il codice dell'app (utils/images.py) non
# cambia di una riga. Il finto S3 parte vuoto, quindi si crea il bucket su cui
# l'app carica le immagini (S3_BUCKET_NAME). Fuori da us-east-1 S3 richiede che
# il bucket dichiari la propria regione (LocationConstraint), altrimenti risponde
# IllegalLocationConstraintException. Uscito dal `with`, il mock si spegne e tutto
# il contenuto sparisce.
@pytest.fixture
def mocked_aws():
    with mock_aws():
        s3 = boto3.client("s3", region_name=os.environ["S3_REGION"])
        s3.create_bucket(
            Bucket=os.environ["S3_BUCKET_NAME"],
            CreateBucketConfiguration={
                "LocationConstraint": os.environ["S3_REGION"]  # type: ignore[typeddict-item]
            },
        )
        yield s3


## Client Fixture
# Il client HTTP che i test usano per chiamare l'app. Richiede db_session e
# mocked_aws, quindi ogni test che lo usa ha database pulito e finto S3.
#
# - dependency_overrides[get_db]: dice a FastAPI "quando una route chiede
#   `get_db`, dalle invece la sessione di test". Cosi' tutte le route con
#   `db: Database` lavorano dentro la transazione che viene annullata a fine test.
# - ASGITransport(app=app): httpx chiama l'app direttamente in memoria, senza
#   aprire porte ne' avviare un server.
# - base_url="http://test": valore fittizio, serve solo a costruire gli URL.
# - AsyncClient (e non il TestClient sincrono di test_demo.py): la sessione async
#   del database vive nell'event loop del test, e il TestClient farebbe girare
#   l'app in un altro thread con un altro event loop.
# - dependency_overrides.clear(): toglie la sostituzione a fine test, cosi' non
#   si propaga agli altri.
@pytest.fixture
async def client(
    db_session: AsyncSession,
    mocked_aws,
) -> AsyncGenerator[AsyncClient]:

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


## Auth Helpers
# Funzioni normali (non fixture): prendono parametri e i test le chiamano quando
# servono. Passano dalle API vere, quindi testano anche gli endpoint.


# Registra un utente con POST /api/users e ne restituisce i dati (JSON).
# L'assert include il testo della risposta, cosi' se la registrazione fallisce
# il messaggio del test mostra subito il motivo.
async def create_test_user(
    client: AsyncClient,
    *,
    username: str = "testuser",
    email: str = "test@example.com",
    password: str = "testpassword123",
    confirm_password: str = "testpassword123",
) -> dict:
    response = await client.post(
        "/api/users",
        json={
            "username": username,
            "email": email,
            "password": password,
            "confirm_password": confirm_password,
        },
    )
    assert response.status_code == 201, (
        f"Failed to create user: {response.text}"
    )
    return response.json()


# Fa il login con POST /api/auth/token e restituisce l'access token (JWT).
# `data=` invia il body come form (non JSON), come richiede OAuth2PasswordRequestForm.
async def login_user(
    client: AsyncClient,
    email: str = "test@example.com",
    password: str = "testpassword123",
) -> str:
    response = await client.post(
        "/api/auth/token",
        data={
            "username": email,
            "password": password,
        },
    )
    assert response.status_code == 200, f"Failed to login: {response.text}"
    return response.json()["access_token"]


# Costruisce l'header HTTP da passare alle route protette, per esempio:
# client.get("/api/users/me", headers=auth_header(token))
def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
