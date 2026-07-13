// When deployed as a Static Web App with this Function App linked as the
// backend, relative /api/* calls are routed automatically - no base URL
// or CORS config needed. For local dev against a standalone func host,
// set API_BASE to e.g. "http://localhost:7071".
const API_BASE = "";

async function loadNotes() {
  const res = await fetch(`${API_BASE}/api/notes`);
  const notes = await res.json();
  const container = document.getElementById("notes");
  container.innerHTML = "";

  notes.forEach((note) => {
    const div = document.createElement("div");
    div.className = "note";
    div.innerHTML = `
      <h3>${escapeHtml(note.title)}</h3>
      <p>${escapeHtml(note.body || "")}</p>
      <small>${new Date(note.created_at).toLocaleString()}</small>
      ${note.attachment_name ? `<br/><a href="${API_BASE}/api/notes/${note.id}/attachment">Download attachment</a>` : ""}
    `;
    container.appendChild(div);
  });
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(",")[1]);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

document.getElementById("note-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const statusEl = document.getElementById("status");
  statusEl.textContent = "";

  const title = document.getElementById("title").value;
  const body = document.getElementById("body").value;
  const fileInput = document.getElementById("attachment");
  const file = fileInput.files[0];

  const payload = { title, body, attachment_name: null, attachment_base64: null };

  if (file) {
    payload.attachment_name = file.name;
    payload.attachment_base64 = await fileToBase64(file);
  }

  try {
    const res = await fetch(`${API_BASE}/api/notes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || "Failed to save note");
    }
    document.getElementById("note-form").reset();
    await loadNotes();
  } catch (err) {
    statusEl.textContent = err.message;
  }
});

loadNotes();
