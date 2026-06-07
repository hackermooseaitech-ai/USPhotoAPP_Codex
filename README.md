# Hacker Moose - AI US Visa Photo Generator

MVP Django app for generating U.S. visa-style 600x600 JPEG photos with white background, preview watermarking, Stripe Checkout, and paid downloads.

## Official Composition Targets

Calibrated against U.S. Department of State guidance:

- Output image: square JPEG, `600x600` px, 300 DPI.
- Head height: top of hair/head to bottom of chin should be `50%` to `69%` of image height.
- Eye height: eye line measured from the bottom should be `56%` to `69%` of image height.
- Background: plain white or off-white. This app normalizes paid output to pure white `#FFFFFF`.

Sources:

- https://travel.state.gov/content/travel/en/us-visas/visa-information-resources/photos/photo-composition-template.html
- https://travel.state.gov/content/travel/en/us-visas/visa-information-resources/photos/digital-image-requirements.html

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Open http://127.0.0.1:8000/

## AI Background Removal

The main requirements install `rembg[cpu]` for portrait background removal. The configured model is `u2net_human_seg`, and the application reuses one model session per Gunicorn worker to avoid loading it for every upload.

MediaPipe remains optional for additional face alignment support:

```powershell
pip install -r requirements-ai.txt
```

If `mediapipe` is unavailable, the app falls back to a center crop. If `rembg` fails, the app uses its edge-connected and OpenCV background-removal fallbacks.

## Environment

Copy `.env.example` to `.env` and fill values as needed.

```powershell
Copy-Item .env.example .env
```

For local MVP testing, Stripe and S3 are optional. Paid downloads work after a real Stripe Checkout payment or after manually marking an order as paid in Django admin.

## Stripe Checkout Setup

1. Create or log in to your Stripe account.
2. Copy your test secret key from Stripe Dashboard > Developers > API keys.
3. Put it in `.env`:

```env
STRIPE_SECRET_KEY=sk_test_xxx
STRIPE_PRICE_CENTS=399
SITE_URL=http://127.0.0.1:8000
```

4. Restart Django, upload a photo, then click Pay and download.
5. Use Stripe test card `4242 4242 4242 4242`, any future expiry, any CVC, and any ZIP.

For webhook fulfillment in local development, install Stripe CLI and run:

```powershell
stripe login
stripe listen --forward-to http://127.0.0.1:8000/stripe/webhook/
```

Copy the printed `whsec_...` value into `.env`:

```env
STRIPE_WEBHOOK_SECRET=whsec_xxx
```

Then restart Django. The app also verifies the returned Checkout Session on the success page, which helps local testing when the webhook listener is not running.

## Member Login Setup

This app uses `django-allauth` for Google OAuth login.

Local callback URLs:

```text
http://127.0.0.1:8000/accounts/google/login/callback/
http://127.0.0.1:8000/accounts/yahoo/login/callback/
```

Render callback URLs:

```text
https://usphotoapp-codex.onrender.com/accounts/google/login/callback/
Add these variables to `.env` locally or Render Environment Variables:

```env
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
```

The Google login button is disabled until the matching client ID and secret are configured.

Local email defaults to Django's console backend, so messages print in the `runserver` terminal instead of sending to an inbox. To send real email, configure SMTP in `.env`, for example:

```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=your-address@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=Hacker Moose <your-address@gmail.com>
```

## Deploy Notes

Render can use `render.yaml` directly. For production:

- The build command preloads the configured rembg model into `.u2net`.
- Keep Gunicorn at one worker on memory-limited instances so the model is not loaded more than once.
- Set `DATABASE_URL` to Neon Postgres.
- Set `DJANGO_ALLOWED_HOSTS` to your Render host.
- Set `SITE_URL` to your public HTTPS URL.
- Set Stripe keys and webhook secret.
- Set `USE_S3=True` plus AWS variables when moving generated files out of local disk.
