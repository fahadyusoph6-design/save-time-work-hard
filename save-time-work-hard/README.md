# Save time, Work hard

Local web app for building job-specific resumes in the style of a default resume and tracking every bid.

## Run (shared server)

On the PC that hosts the app, double-click `start.bat`. The first run installs what it needs and asks
once (Windows admin prompt) to open port 8000 in the firewall. The window prints the address to give
everyone else, e.g. `http://192.168.2.131:8000`. Keep that window open while people work.

- The server PC must stay on and awake (Settings → Power → Sleep: Never).
- The network must be set to **Private** (Settings → Network → Properties), or the firewall rule won't apply.
- Other PCs only need a browser.
- For use on this PC only: `set HOST=127.0.0.1` before `start.bat`.

Admin login: `icaroosu` / `welcome!@#123`. Change it after the first login (Profile → Change password),
because anyone on the network can reach the login page.

Default resumes are normally **uploaded** from the browser and stored in `data\resumes\<user>\` on the
server; resumes generated from them are saved in that same folder and downloaded to the user's PC.
A path on the server or a shared network folder (`\\server\Resumes\...`) also works.

Back up the `data` folder to keep accounts, history and saved resumes.

## Workflow

1. Admin creates accounts (Admin → Accounts). Users log in with their e-mail.
2. On the dashboard, add a **default resume** (upload a `.docx`) and select it.
3. **Start bid** → paste the styled resume text and the JD (plus job URL). Job title, company and jobsite
   are autofilled from the JD/URL; date/time are autofilled; the filename is editable.
4. **Download and Save** → the `.docx` is built with the default resume's styling, saved in the default
   resume's folder, downloaded, and recorded in the history.

## Development

```
cd backend && ..\.venv\Scripts\python -m uvicorn main:app --reload --port 8000
cd frontend && npm run dev        # http://localhost:5173, proxies /api to :8000
cd frontend && npm run build      # rebuild what start.bat serves
```

Data (users, history) lives in `data/app.db`.

## How styling works

`backend/resume_builder.py` classifies each paragraph of the default resume (name, contact, section heading,
job/date line, bullet, body) and keeps one as a prototype per role. The pasted resume is classified the same
way, and each paragraph is rebuilt from its role's prototype — fonts, sizes, colours, spacing, borders, tab
stops, bullet numbering, margins, headers and footers all come from the default resume. Bold/italic inside
body text and bullets is kept from the pasted text.

Limits: layouts built from tables, text boxes or multiple columns are flattened into a single column;
images in the default resume's body are not carried over (header/footer images are).
