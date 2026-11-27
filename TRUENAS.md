# Installing Cookbook on TrueNAS SCALE

Tested setup: TrueNAS SCALE 24.10 (Electric Eel) or newer, which runs apps with Docker.
Time needed: about 15 minutes. In the examples the pool is called `tank`; use your own pool name.

## How it works

GitHub builds the app image every time the code on the `main` branch changes and publishes it as
`ghcr.io/pringsen/cookbook:latest`. TrueNAS downloads that image; nothing is built on the NAS.
(Prefer not to use GitHub? See "Without GitHub" at the end.)

## 1. Let TrueNAS download the image (once)

New images on GitHub's registry are private. TrueNAS can't log in to it from an "Install via YAML" app, so
make the image public. Only the built image becomes public; the repository with the code stays private, and the
image contains no passwords or keys (those live on the NAS).

1. Open [github.com/pringsen?tab=packages](https://github.com/pringsen?tab=packages) and click **cookbook**.
2. **Package settings** (right side) → **Danger Zone** → **Change visibility** → **Public**, type `cookbook`, confirm.

## 2. Create the datasets

In **Datasets**, select your pool and add:

| Dataset | Preset | Holds |
|---|---|---|
| `tank/apps/cookbook` | Apps | parent folder |
| `tank/apps/cookbook/data` | Apps | uploaded photos and the app's secret key |
| `tank/apps/cookbook/postgres` | **Generic** | the database |

(If `tank/apps` doesn't exist yet, create it first with the Apps preset.)
The database folder uses the Generic preset because the Postgres container needs to set its own owner and permissions there.

## 3. Choose a database password

In **System → Shell** run `openssl rand -hex 24` and copy the result. It's letters and digits only, which the
app needs.

## 4. Install the app

1. Go to **Apps → Discover Apps**, click the **⋮** menu (top right) → **Install via YAML**.
2. Name: `cookbook`.
3. Paste the contents of `truenas-app.yaml` and edit it:
   - replace `tank` with your pool name (3 places),
   - replace both `CHANGE_ME_DB_PASSWORD` with the password from step 3,
   - check `TZ` (set to `Europe/Vienna`),
   - change `"8080:8000"` to `"<port>:8000"` if port 8080 is taken.
4. Click **Save**. TrueNAS downloads the images; after a minute or two the app shows as **Running**.

## 5. First start

Open `http://<your-NAS-IP>:8080`. You'll be asked to create the first account, which becomes the admin.
Under **⚙ Settings** you can:

- paste your **Anthropic API key** for photo import (create one at console.anthropic.com → API keys; a photo usually costs a few cents),
- add accounts for other people in your household.

## Updating to a new version

When a new version is pushed to GitHub, wait until its build is green under the repository's **Actions** tab
(about 3 minutes), then in **Apps** select cookbook → **Stop**, then **Start**. `pull_policy: always` makes
TrueNAS fetch the newest image on every start. (If it doesn't, use **Edit** → **Save** without changes, or run
`sudo docker pull ghcr.io/pringsen/cookbook:latest` in the shell first.)

To go back to an older build, replace `:latest` in the YAML with the build's `sha-…` tag from the package page.

Your recipes, photos and calendar live in the `data` and `postgres` datasets and are not touched by updates.
New database tables and columns are created automatically on start.

## Backups

- Add a **Periodic Snapshot Task** (Data Protection) for `tank/apps/cookbook` with "Recursive" ticked. For a fully consistent database snapshot, stop the app first or keep a daily JSON export.
- In the app, **Settings → Backup → Download export** saves all recipes, cookbooks and the cooking calendar as JSON.

## Access from outside your home

The app has its own login, but it is meant for your home network. To use it on the go, prefer a VPN such as
Tailscale or WireGuard (both available as TrueNAS apps). If you put it behind a reverse proxy with HTTPS
(e.g. Nginx Proxy Manager), set `SECURE_COOKIES: "true"` in the YAML.

## Troubleshooting

- **App keeps restarting / "Could not connect to the database":** the password in `POSTGRES_PASSWORD` and in `DATABASE_URL` must match and contain only letters and digits. If you changed the password after the first start, the database still has the old one: either put the old one back, or stop the app, empty the `postgres` dataset (this deletes all data!) and start again.
- **Postgres error "Operation not permitted" on its data folder:** the `postgres` dataset must use the Generic preset (see step 1). Edit its permissions, choose ACL type POSIX, and save.
- **"denied" or "unauthorized" when pulling `ghcr.io/pringsen/cookbook`:** the package is still private (step 1), or the first build hasn't finished yet (check the repository's Actions tab).
- **Logs:** Apps → cookbook → the container's **View Logs** icon.
- **Photo import says the key was rejected:** check the key under Settings, and that your Anthropic account has credit.

## Without GitHub

Copy the code to `tank/apps/cookbook/src` (SMB share or `unzip` in the shell), build the image on the NAS with
`sudo docker build -t cookbook:local /mnt/tank/apps/cookbook/src`, and install with `truenas-app-local.yaml`
instead. To update, replace the files, build again, then Stop and Start the app.
