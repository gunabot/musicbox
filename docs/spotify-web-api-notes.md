# Spotify Web API Notes (Musicbox)

Last updated: 2026-03-01

## Why this doc exists
- Clarify Spotify token behavior in plain language.
- Document which Web API endpoints this project uses.
- Track February/March 2026 migration changes and how this repo handles them.

## Token model (important)
- `access_token`:
  - short-lived bearer token used for API calls.
  - Spotify token response includes `expires_in` (typically ~3600 seconds).
  - UI "Access Token Expiry" refers to this token only.
- `refresh_token`:
  - long-lived token used to mint a new access token.
  - no reliable expiry timestamp is provided in normal token responses.
  - if invalid/revoked (`invalid_grant`), user must reconnect once.

## Current architecture decision (anti-race)
- Web service (`spotify_auth.py`) is the single owner for token refresh/write.
- Import worker (`scripts/spotify-cache-fetch`) receives an access token and runs in read-only token mode.
- This avoids refresh-token write races between multiple processes.
- OAuth state is persisted in SQLite (`config/musicbox.db`).
- Legacy JSON OAuth state is auto-migrated on startup (non-destructive by default).

## Endpoints used by Musicbox
- OAuth:
  - `GET https://accounts.spotify.com/authorize`
  - `POST https://accounts.spotify.com/api/token`
- User/profile:
  - `GET /v1/me`
- Search:
  - `GET /v1/search`
- Playback transfer/control:
  - `GET /v1/me/player/devices`
  - `PUT /v1/me/player`
  - `PUT /v1/me/player/play`
  - `PUT /v1/me/player/pause`
- Metadata for import:
  - `GET /v1/tracks/{id}`
  - `GET /v1/albums/{id}`
  - `GET /v1/albums/{id}/tracks`
  - `GET /v1/playlists/{id}`
  - `GET /v1/playlists/{id}/items`

## Migration notes (Feb 2026 -> Mar 2026)
- Spotify migration guide date for existing Dev Mode apps: March 9, 2026.
- Important changes for this project:
  - search limit is now capped at 10 per type.
  - playlist item endpoint/payload uses `/playlists/{id}/items` with `item` wrapper.
  - some profile fields may no longer be available in all modes.
- Repo changes applied:
  - backend and frontend search now use max 10.
  - importer uses `/playlists/{id}/items` and supports both `item` and legacy `track` wrappers.
  - search playlist parsing supports both `tracks.total` and `items.total`.

## Observability in UI
- Access token expiry is shown in Settings.
- If refresh token is revoked, API returns:
  - "Spotify authorization expired. Please reconnect Spotify in Settings."
- Reconnect flow:
  - Settings -> Connect Spotify -> approve -> close popup.

## Policy and compliance note
- Spotify Web API is for metadata/control; downloading or stream-ripping is restricted by Spotify terms/policy.
- This project uses a local cache import flow for personal appliance use. Review your own compliance requirements.

## Official references
- Migration guide:
  - https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide
- Refresh token tutorial:
  - https://developer.spotify.com/documentation/web-api/tutorials/refreshing-tokens
- Search reference:
  - https://developer.spotify.com/documentation/web-api/reference/search
- Playlist items reference:
  - https://developer.spotify.com/documentation/web-api/reference/get-playlists-items
- OAuth 2.0 spec (RFC 6749):
  - https://datatracker.ietf.org/doc/rfc6749/
