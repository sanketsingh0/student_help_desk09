# StudySpace – Student Help Desk

A Flask website where registered students access study resources through Google Drive links. Only the administrator can add, edit, or remove material links. administrator have only access to change the user or any one change password 

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

## Managing users

- There is **no self-service password reset** (no OTP flow). Users who forget their password click **Forgot password?** on the login page and are directed to contact the administrator.
- Set `ADMIN_EMAIL` and `ADMIN_PASSWORD` in your `.env` file (or Render environment). The app reads the admin credentials **only from the environment** — nothing is hard-coded — and creates or updates the admin account on every start.
- The **administrator** can manage all user accounts from the **Admin panel** → **Manage users**.
- The user management module provides:
  - A **table view** of all registered users (ID, name, email, role).
  - A **search box** to filter users by name or email.
  - **Edit** — change a user's name, email, role (student/admin), or set a new password (minimum 8 characters).
  - **Delete** — remove a student account (admin accounts and your own account cannot be deleted).

## Student tasks panel and Teacher panel

Students can log the college assignments/projects they are working on, and teachers can review and grade them. The data is stored in the same database (SQLite locally, PostgreSQL on Render).

- **Students** — after logging in, click **My tasks**:
  - Add tasks with a **subject code** (e.g. `CS301`), subject name, **category** (Assignment / Project / Lab work / Practical / Quiz, etc.), a title, a description, and work-done notes.
  - **Submit work by link** — just like admins add material links, students paste a Google Drive link to their assignment/project (from the task's *Submit link* box or the add/edit form). The submitted link appears in the teacher panel for review.
  - **Filter** their own tasks by subject code.
  - See the current status badge and a **progress % bar** set by the teacher.
- **Student profile module** — on the top right of the **My tasks** dashboard every student has a profile card and can update their **full name, roll number, course, section, branch, and year** (the email shown there is their login id and cannot be changed). The name and roll number are copied into every task the student logs (`student_tasks.student_name` / `student_roll`), so teachers always see who submitted the work. The administrator can also set the roll number from **Admin panel → Manage users → Edit**.
- **Teachers** — the administrator marks an account as a **Teacher** from **Admin panel → Manage users → Edit → Teacher**. Teachers then see the **Teacher panel**:
  - Every student's logged task with the student's name, email, and rolling ID.
  - **Filter by subject code** and/or by a specific student.
  - **Mark** each task as Pending / In progress / **Completed**, set a **0–100 % progress range**, and leave a private remark.
  - Stats cards (total, completed, in progress, average progress).
- **Work completion report** (`teacher/report`, also linked in the nav + teacher panel) — a `report_work` table showing only completed work: **student name, roll number, task title, subject code, teacher remark, and submission date**. Each completed task appears automatically when the teacher saves it, and the report can be filtered by subject code or student.

Note: `ADMIN_PASSWORD` for Render as well as `DATABASE_URL` configure the deployed database — all task data is saved there.

## Deploy on Render

1. Upload this project to a GitHub repository.
2. In Render, select **New +** → **Blueprint** and connect the repository. Render detects `render.yaml`.
3. Enter `DRIVE_FOLDER_URL`, `ADMIN_EMAIL`, and `ADMIN_PASSWORD` when asked. Render generates `SECRET_KEY` automatically.
4. For welcome emails, add `BREVO_API_KEY` and `SENDER_EMAIL` (create a free Brevo account, verify a sender inbox, and paste your [API key](https://app.brevo.com/settings/keys/api)).
5. Allowlist the Render server IP in Brevo under [Authorised IPs](https://app.brevo.com/security/authorised_ips) (choose **No restriction** if your IP can change).
6. Click **Apply**. Render builds and deploys the website.

You can also create a **Web Service** manually with build command `pip install -r requirements.txt` and start command `gunicorn app:app`.
