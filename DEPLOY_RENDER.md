# Deploy CommerceAI on Render (free demo)

This project can run as a single Python web service. The standard demo runtime uses Python's standard library and the bundled intent model; optional Rasa and training dependencies are not needed.

## 1. Put the project on GitHub

1. Create a **public** GitHub repository named `CommerceAI` (or keep it private and authorize Render to access it).
2. Upload the **contents of this CommerceAI folder** to the repository root. `run.py`, `render.yaml`, `commerce/`, `models/`, and `static/` should be at the top level. Do not upload the outer ZIP file as the repository contents.
3. Commit the files to the `main` branch.

## 2. Create the public service

1. Sign in at https://render.com/ and connect your GitHub account.
2. Choose **New → Blueprint** (or create a **New → Web Service** from the repository).
3. If using Blueprint, select the repository containing `render.yaml` and apply the configuration.
4. If creating a Web Service manually, use:
   - Runtime: **Python 3**
   - Build command: `echo "No third-party runtime dependencies required"`
   - Start command: `python run.py`
   - Instance type: **Free**
   - Environment variable `HOST`: `0.0.0.0`
   - Health check path: `/api/health`
5. Wait for the deployment to finish. Render will show a URL similar to `https://commerceai-demo.onrender.com`. Open it and test the catalogue and chatbot.

## 3. Share with your professor

Send the generated `https://....onrender.com` URL. The first visit after inactivity can take about a minute because free Render services sleep after 15 minutes without traffic.

## Demo limitations

- This is an academic prototype with fictional stores and synthetic customers, orders, stock, payment/refund statuses, and policies. It is not connected to real commerce providers.
- The staff PINs shown in the project README are demo credentials only. Do not add real customer data, passwords, API keys, or payment details.
- Render's free filesystem is ephemeral. The demo SQLite database and changes made during a session may reset after a restart, redeploy, or sleep cycle. This is acceptable for a short professor evaluation; use a persistent database before treating it as a long-running service.
- The service is publicly accessible to anyone who has the link.

## Local use remains unchanged

On macOS, continue using `Start_CommerceAI.command`. On Windows, use `Start_CommerceAI.bat`.
