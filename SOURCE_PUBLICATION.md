# Source publication

The public tree contains application source, synthetic tests, example
configuration, deployment scripts, and the MIT license. Company branding,
internal job descriptions, live service addresses, credentials, browser profiles,
databases, test scratch directories, and internal documents are excluded.

Frontend assets are built from source with `npm ci` and `npm run build`; generated
`dist` files are not published as source. Deploy from source or with Docker
Compose. Product activation, device binding, and desktop installer tooling have
been removed; the repository's MIT license remains unchanged.

See `docs/DATA_PRIVACY.md` for runtime data retention. A clean current tree does
not by itself remove earlier versions from Git history, forks, or caches.
