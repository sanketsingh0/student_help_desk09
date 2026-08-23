# StudySpace – Student Help Desk

A Flask website where registered students access study resources through Google Drive links. Only the administrator can add, edit, or remove material links.

## Add your Google Drive link

1. In Google Drive, open the folder containing your study materials.
2. Click **Share** and set access to **Anyone with the link – Viewer**.
3. Copy the folder link.
4. The administrator signs in and adds each folder or file link from the Admin panel.
5. Set `DRIVE_FOLDER_URL` in Render for the starter links. The admin can replace them later.

## Accounts

- Students must **Register** and then **Log in** to access materials.
- The first admin account is created automatically. Set `ADMIN_EMAIL` and a strong `ADMIN_PASSWORD` in Render before deployment. Never use the default password.
- The admin logs in from the normal login page and is redirected to the Admin panel.

The website protects the links until a user logs in. However, students can still share a Drive URL after opening it, so configure Google Drive sharing permissions too.

## Run locally

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`.

## Sending welcome email

The app tries these providers in order until one succeeds:

1. **Resend** – set `RESEND_API_KEY` and `EMAIL_FROM`. Free tier can only send to your own inbox unless you verify a domain at [resend.com/domains](https://resend.com/domains).
2. **Brevo (recommended)** – set `BREVO_API_KEY` and `SENDER_EMAIL`. Free tier allows **300 emails/day** with no domain needed; just verify the sender address once in the Brevo dashboard. `SENDER_NAME` is optional (defaults to "StudySpace").
   - **Important:** If you get a `401 unrecognised IP address` error from Brevo, allowlist your server IP at [app.brevo.com/security/authorised_ips](https://app.brevo.com/security/authorised_ips) (on Render free tier, set it to **No restriction** since the outbound IP can change).
3. **Gmail SMTP** – set `EMAIL` and `APP_PASSWORD` (a Gmail app password). Works locally, but note Render's free tier **blocks outbound SMTP**, so this fallback generally only works when running locally.

## Managing user passwords

- There is **no self-service password reset** (no OTP flow).
- The **administrator** can change any user's password from the **Admin panel** under **Manage user passwords**.
- The admin enters a new password (minimum 8 characters) for the selected user and clicks **Change password**.

## Deploy on Render

1. Upload this project to a GitHub repository.
2. In Render, select **New +** → **Blueprint** and connect the repository. Render detects `render.yaml`.
3. Enter `DRIVE_FOLDER_URL`, `ADMIN_EMAIL`, and `ADMIN_PASSWORD` when asked. Render generates `SECRET_KEY` automatically.
4. For welcome emails, add `BREVO_API_KEY` and `SENDER_EMAIL` (create a free Brevo account, verify a sender inbox, and paste your [API key](https://app.brevo.com/settings/keys/api)).
5. Allowlist the Render server IP in Brevo under [Authorised IPs](https://app.brevo.com/security/authorised_ips) (choose **No restriction** if your IP can change).
6. Click **Apply**. Render builds and deploys the website.

You can also create a **Web Service** manually with build command `pip install -r requirements.txt` and start command `gunicorn app:app`.
