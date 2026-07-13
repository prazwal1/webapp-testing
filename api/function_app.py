"""
Function App API for a minimal "Notes" app.

Scenario: create a note with a title/body and an optional file attachment.
Note metadata goes to PostgreSQL, attachments go to Blob Storage, and the
DB connection string is pulled from Key Vault on cold start (not stored as
a plaintext app setting).

Routes are exposed at /api/notes by default - when this Function App is
linked as the backend to a Static Web App, the frontend can call
`/api/notes` directly and Static Web Apps routes it through automatically
(no CORS config needed in that setup).
"""

import logging
import os
import json
import uuid
import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from azure.storage.blob import BlobServiceClient
import psycopg2
from psycopg2.extras import RealDictCursor

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

credential = DefaultAzureCredential()

KEY_VAULT_URL = os.environ["KEY_VAULT_URL"]
STORAGE_ACCOUNT_URL = os.environ["STORAGE_ACCOUNT_URL"]
BLOB_CONTAINER = os.environ.get("BLOB_CONTAINER", "attachments")

_db_conn_string = None  # cached across warm invocations


def get_db_connection_string() -> str:
    """Fetch the DB connection string from Key Vault once per cold start."""
    global _db_conn_string
    if _db_conn_string is None:
        client = SecretClient(vault_url=KEY_VAULT_URL, credential=credential)
        _db_conn_string = client.get_secret("db-connection-string").value
    return _db_conn_string


def get_db_connection():
    return psycopg2.connect(get_db_connection_string(), sslmode="require", connect_timeout=5)


# ---------------------------------------------------------------------------
# GET /api/notes - list all notes
# ---------------------------------------------------------------------------
@app.route(route="notes", methods=["GET"])
def list_notes(req: func.HttpRequest) -> func.HttpResponse:
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, title, body, attachment_name, created_at FROM notes ORDER BY created_at DESC;")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return func.HttpResponse(
            json.dumps(rows, default=str),
            mimetype="application/json",
            status_code=200,
        )
    except Exception as e:
        logging.exception("list_notes failed")
        return func.HttpResponse(json.dumps({"error": str(e)}), status_code=500)


# ---------------------------------------------------------------------------
# POST /api/notes - create a note, optionally with a base64 attachment
# Body: {"title": str, "body": str, "attachment_name": str|null, "attachment_base64": str|null}
# ---------------------------------------------------------------------------
@app.route(route="notes", methods=["POST"])
def create_note(req: func.HttpRequest) -> func.HttpResponse:
    try:
        payload = req.get_json()
        title = payload.get("title")
        body = payload.get("body", "")
        attachment_name = payload.get("attachment_name")
        attachment_base64 = payload.get("attachment_base64")

        if not title:
            return func.HttpResponse(json.dumps({"error": "title is required"}), status_code=400)

        note_id = str(uuid.uuid4())
        stored_attachment_name = None

        if attachment_name and attachment_base64:
            import base64
            blob_service = BlobServiceClient(account_url=STORAGE_ACCOUNT_URL, credential=credential)
            container_client = blob_service.get_container_client(BLOB_CONTAINER)
            if not container_client.exists():
                container_client.create_container()

            stored_attachment_name = f"{note_id}-{attachment_name}"
            blob_client = container_client.get_blob_client(stored_attachment_name)
            blob_client.upload_blob(base64.b64decode(attachment_base64), overwrite=True)

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO notes (id, title, body, attachment_name, created_at) "
            "VALUES (%s, %s, %s, %s, now());",
            (note_id, title, body, stored_attachment_name),
        )
        conn.commit()
        cur.close()
        conn.close()

        return func.HttpResponse(
            json.dumps({"id": note_id, "status": "created"}),
            mimetype="application/json",
            status_code=201,
        )
    except Exception as e:
        logging.exception("create_note failed")
        return func.HttpResponse(json.dumps({"error": str(e)}), status_code=500)


# ---------------------------------------------------------------------------
# GET /api/notes/{note_id}/attachment - stream the attachment back
# ---------------------------------------------------------------------------
@app.route(route="notes/{note_id}/attachment", methods=["GET"])
def get_attachment(req: func.HttpRequest) -> func.HttpResponse:
    try:
        note_id = req.route_params.get("note_id")
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT attachment_name FROM notes WHERE id = %s;", (note_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row or not row["attachment_name"]:
            return func.HttpResponse(json.dumps({"error": "no attachment for this note"}), status_code=404)

        blob_service = BlobServiceClient(account_url=STORAGE_ACCOUNT_URL, credential=credential)
        blob_client = blob_service.get_container_client(BLOB_CONTAINER).get_blob_client(row["attachment_name"])
        data = blob_client.download_blob().readall()

        return func.HttpResponse(data, status_code=200, mimetype="application/octet-stream")
    except Exception as e:
        logging.exception("get_attachment failed")
        return func.HttpResponse(json.dumps({"error": str(e)}), status_code=500)


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------
@app.route(route="health", methods=["GET"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(json.dumps({"status": "ok"}), mimetype="application/json", status_code=200)
