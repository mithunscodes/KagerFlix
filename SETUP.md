# KagerFlix Render Deployment Guide

## Initial Setup Steps

### 1. Generate a Secret Key
Run this locally to generate a secure secret key:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```
Keep this secret key safe - you'll need it for Render environment variables.

### 2. Create Admin Account
When you first deploy to Render:
1. Visit `https://your-app.onrender.com/setup-admin`
2. Create your admin account with a strong password
3. Keep these credentials secure - they're needed to delete videos

### 3. Environment Variables on Render
Go to your Render dashboard and set these environment variables:

```
SECRET_KEY=<your-generated-secret-key>
FLASK_ENV=production
FLASK_DEBUG=False
AWS_S3_BUCKET=<optional-bucket-name>
AWS_REGION=us-east-1
```

### 4. Deploy on Render
1. Connect your GitHub repository to Render
2. Select Python as the runtime
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app`

## User Roles & Permissions

### Admin
- ✅ View all videos
- ✅ Upload videos
- ✅ Delete any video
- ✅ See platform statistics

### Contributors (Signed-up Users)
- ✅ View all videos
- ✅ Upload videos
- ✅ Edit their own video info
- ✅ Cannot delete videos

### Guests (Not Signed In)
- ✅ View all videos
- ❌ Cannot upload videos
- ❌ Cannot delete videos

## Installation for Local Development

```bash
# Create virtual environment
python -m venv venv
source venv/Scripts/activate  # On Windows

# Install dependencies
pip install -r requirements.txt

# Set up database
python -c "from app import app, db, init_db; init_db(app)"

# Run development server
python app.py
```

Then visit `http://localhost:5000/setup-admin` to create your first admin account.

## Security Checklist

- [ ] Changed SECRET_KEY from default value
- [ ] Created admin account with strong password
- [ ] Set FLASK_DEBUG=False in production
- [ ] Configured HTTPS on Render (automatic)
- [ ] Updated requirements.txt is up to date
- [ ] Database backups are configured (if using cloud DB)

## Troubleshooting

### No admin exists error
If you can't create admin account, check that no admin user exists in the database. Delete the database and restart if needed.

### Login not working
Ensure SECRET_KEY is the same across all instances (especially important for horizontal scaling).

### Password hashing issues
Make sure `werkzeug` is properly installed: `pip install --upgrade werkzeug`

## Video Deletion Policy

Only admins can delete videos. This prevents accidental or malicious deletion. To delete:
1. Log in as admin
2. Go to Dashboard
3. Click the delete button on any video
4. Confirm the deletion

**Warning:** Deleted videos cannot be recovered!
