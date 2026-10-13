# frontend

Next.js 14 dashboard. See the [root README](../README.md) for the full stack.

```bash
npm install
echo NEXT_PUBLIC_API_URL=http://localhost:8000 > .env.local
npm run dev            # http://localhost:3000
npx tsc --noEmit && npm run build
```

Routes live under `src/app/dashboard/*`; API calls go through `src/lib/api.ts` (JWT injection +
refresh). Login with the seeded account `demo@example.com / Test123!`.
