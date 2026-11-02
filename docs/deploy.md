# Deploying to Google Cloud Run

[Back to the README](../README.md)

These steps are for someone new to Google Cloud. They use Cloud Shell, a terminal in your browser that already has the `gcloud` command and is signed in to your account, so you don't need to install anything.

**Keep the public site in demo or preview mode.** A container on Cloud Run doesn't keep files between restarts, so live mode would lose its SQLite data. Live mode on Cloud Run would need a database outside the container (see [the production path](production.md)).

## Start each Cloud Shell session in the project folder

Cloud Shell can return to your home folder after a break. Before running any command below, go back into the project and get the latest code:

```bash
cd Sandbox-to-Shipped && git pull
```

## Deploy the demo

1. Go to https://console.cloud.google.com and sign in. If you don't have a project yet, create one from the project picker at the top of the page. Cloud Run needs billing turned on for the project.
2. Click the **Activate Cloud Shell** button (a terminal icon) at the top right. A terminal opens at the bottom of the page.
3. Get the code and deploy it. Paste these into Cloud Shell:

```bash
git clone https://github.com/jmims-workflow/Sandbox-to-Shipped.git && cd Sandbox-to-Shipped
```

```bash
gcloud run deploy sandbox-to-shipped --source . --region us-east1 --allow-unauthenticated --set-env-vars STS_MODE=demo
```

4. If `gcloud` asks to turn on APIs (such as Cloud Run, Cloud Build or Artifact Registry) or to create a repository for the built image, answer `y`. Building from source uses the `Dockerfile` in the repository.
5. When it finishes, it prints a **Service URL**. Open it. You should see Request a tool with "Demo: sample data" in the sidebar.

Cloud Run sets the `PORT` variable for you, and the app listens on it.

## Run the public site in live preview mode

Live preview shows real Claude results without saving anything. The API key is stored in Secret Manager, so it never appears in your command history, the service settings or the browser.

1. In Cloud Shell, turn on Secret Manager:

```bash
gcloud services enable secretmanager.googleapis.com
```

2. Store your Claude API key as a secret named `anthropic-api-key`. This asks for the key without showing it on screen or saving it in your command history. Paste the key and press Enter:

```bash
read -s -p "Paste the Claude API key: " KEY && echo
```

```bash
printf %s "$KEY" | gcloud secrets create anthropic-api-key --data-file=- && unset KEY
```

3. Give the Cloud Run service permission to read that secret. By default a Cloud Run service runs as the project's default compute service account, `PROJECT_NUMBER-compute@developer.gserviceaccount.com`. This finds your project number and grants the Secret Manager Secret Accessor role on this one secret:

```bash
PROJECT_NUMBER=$(gcloud projects describe $(gcloud config get-value project) --format='value(projectNumber)')
```

```bash
gcloud secrets add-iam-policy-binding anthropic-api-key --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" --role="roles/secretmanager.secretAccessor"
```

4. Deploy in preview mode, with the key passed as a secret and at most one running copy of the app. One copy keeps the daily count accurate, because each copy counts on its own:

```bash
gcloud run deploy sandbox-to-shipped --source . --region us-east1 --allow-unauthenticated --set-env-vars STS_MODE=preview --update-secrets=ANTHROPIC_API_KEY=anthropic-api-key:latest --max-instances 1
```

5. Open the Service URL. The sidebar now says "Live preview: real Claude, nothing saved". To change the limits, add them to `--set-env-vars`, for example `--set-env-vars STS_MODE=preview,STS_DAILY_CLAUDE_CALLS=50`. All the settings are in [configuration](configuration.md).

6. **Set a monthly spend limit as a backstop.** The app's limits reset when the server restarts, so also cap spending on the Claude side. In the Claude Console, open the **Billing** page (https://platform.claude.com/settings/billing), find **Spend limits** and click **Set limit** (or **Adjust limit**). Pick a monthly amount you're comfortable with. Requests stop for the rest of the month once it's reached, and the site falls back to the sample results.

## Replace the Claude key when it expires

The key expires every 90 days. Replace it without ever showing it on screen. Start in the project folder (`cd Sandbox-to-Shipped && git pull`), then:

1. Create a new key in the Claude Console.
2. Add it as a new version of the secret. `read -s` keeps the key off the screen and out of your command history:

```bash
read -s -p "Paste the new Claude API key: " KEY && echo
```

```bash
printf %s "$KEY" | gcloud secrets versions add anthropic-api-key --data-file=- && unset KEY
```

3. List the versions and disable the old one. Replace `OLD_VERSION` with the old version's number from the list (the new one is the highest):

```bash
gcloud secrets versions list anthropic-api-key
```

```bash
gcloud secrets versions disable OLD_VERSION --secret=anthropic-api-key
```

4. Deploy again so the service picks up the new version:

```bash
gcloud run deploy sandbox-to-shipped --source . --region us-east1 --allow-unauthenticated --set-env-vars STS_MODE=preview --update-secrets=ANTHROPIC_API_KEY=anthropic-api-key:latest --max-instances 1
```

5. Open the site and try a match check to confirm it works, then delete the old key in the Claude Console.

## Run with Docker

```bash
docker build -t sandbox-to-shipped .
```

```bash
docker run -p 8080:8080 -e STS_MODE=demo sandbox-to-shipped
```

The container serves on `PORT` (default 8080). `/health` returns `ok`.
