<!-- LOVABLE:BEGIN -->
> [!IMPORTANT]
> This project is connected to [Lovable](https://lovable.dev). Avoid rewriting
> published git history — force pushing, or rebasing/amending/squashing commits
> that are already pushed — as it rewrites history on Lovable's side and the
> user will likely lose their project history.
>
> Commits you push to the connected branch sync back to Lovable and show up in
> the editor, so keep the branch in a working state.
<!-- LOVABLE:END -->

- All backend calls go through src/lib/api.ts (FastAPI at VITE_API_BASE_URL); pages read fields defensively via pick()/asList() because the backend schema is authoritative and wasn't available at build time.
- Dashboard pages live under the pathless `_app` layout (ssr: false) because the session token is in localStorage.
