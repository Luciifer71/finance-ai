# Mobile development handoff — Finance AI

Owner: Mobile/UI developer (partner)  
Branch: `feat/mobile-foundation`  
Stack: Expo SDK 54, React Native, Expo Router and TypeScript  
Scope: Initial UI only; no real bank account connections.

## 1. Prepare the Windows laptop

Install Git, Node.js 22 LTS (and npm), and Visual Studio Code. Run in PowerShell:

```powershell
node --version
npm --version
git --version
```

Accept the private GitHub repository collaborator invitation first. Then clone and select the dedicated branch:

```powershell
git clone https://github.com/Luciifer71/finance-ai.git
cd finance-ai
git fetch origin
git switch --track origin/feat/mobile-foundation
```

If the branch is already selected, use `git branch --show-current` to confirm it.

## 2. Install and check the mobile project

```powershell
cd apps/mobile
npm install
npm run typecheck
npx expo start
```

The existing project includes `app/index.tsx` (initial dashboard) and `app/_layout.tsx` (navigation shell). Use Expo Go on a supported phone for the basic UI, or a supported simulator/environment when available. Expo Go support depends on its installed SDK version. Native features will require a development build later.

For the first day, no Docker, Python, PostgreSQL, bank credentials, paid Apple Developer account or Mac is required to work on the UI.

## 3. First UI task

Improve the existing dashboard using fabricated placeholder values only:
- Keep the three sections: Balance, Expenses and Goals.
- Create a small reusable UI component for the existing dashboard cards (for example `components/DashboardCard.tsx`).
- Keep screens accessible: readable contrast, labels and spacing.
- Show clear **not connected** / **no data** empty states. Never display a fabricated balance as if it came from a bank.
- Keep navigation simple; do not wire real authentication or UPI integrations yet.
- Do not remove or break the existing app or lint/type checks.

Start with existing files and avoid installing extra UI libraries without discussing the tradeoff with the other developer.

## 4. Commit, push and review

From the repository root:
```powershell
git status
git branch --show-current
git add apps/mobile
git commit -m "feat(mobile): refine initial dashboard components"
git push -u origin feat/mobile-foundation
```

Create a pull request targeting `main`. Check **Mobile checks** and request review before merging. Do not merge or delete a branch until review and checks are complete.

## 5. Handoff checklist

- [ ] GitHub invitation accepted and repository cloned
- [ ] `feat/mobile-foundation` checked out
- [ ] `npm install` completed
- [ ] `npm run typecheck` passed
- [ ] Initial Expo screen visible
- [ ] First dashboard UI change pushed
- [ ] PR opened against `main`

## Working agreements

Two developers: backend/AI and mobile/UI. Work in separate feature branches, use small reviewed pull requests, communicate API shape before integration, and never commit `.env`, access tokens or personal financial information. All bank and transaction data in UI mocks must be synthetic. 
