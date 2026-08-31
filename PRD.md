# MAPO — Product Requirements & Progress

## Original Problem Statement
Build a modern, highly interactive **3D web application** for a personalized nutrition & calorie tracking startup (**MAPO**). Instagram-style social feed: interactive 3D hero (floating food/macro spheres that break into Protein/Carbs/Fats), stories tray, interactive feed cards (double-tap heart, bookmark, "Log Calorie"), full-screen Spatial Food Inspector with floating macro tooltips, particle nutrient background, glassmorphism UI. Built on React + Three.js/React-Three-Fiber + Tailwind + Framer Motion.

## User Choices (confirmed)
- Use the user's real Indian food database (1028 items) + alcoholic drinks DB.
- Integrate the user's Python diet calculator (BMI/BMR/TDEE + macro + 5-slot meal plan) as a real "Get My Diet Plan" feature.
- Integrate the user's rule-based **Hinglish/English AI Nutrition Coach** chatbot as-is (no LLM).
- Email/password auth (JWT Bearer).
- Theme: **neon pink / black / cyan** cyberpunk (final; iterated from emerald→orange→neon).

## Architecture
- **Backend**: FastAPI + MongoDB (motor). Modules: `server.py`, `auth.py` (JWT+bcrypt), `nutrition.py`, `mapo_chatbot.py`, `feed.py`, `mapo_data.py` (loads CSVs from `/app/backend/data`).
- **Frontend**: React 19 + react-three-fiber v9 + drei v10 + Tailwind + Framer Motion + sonner. Auth via localStorage Bearer token.
- All backend routes under `/api`. Frontend uses `REACT_APP_BACKEND_URL`.

## Implemented (2026-06 / iteration 1)
- Auth: register/login/me/profile, admin seed (coach@mapo.app / MAPO@2026), bcrypt + JWT.
- Diet plan generator endpoint `/api/diet/plan` (real calculations + meal plan from food DB).
- Coach chat `/api/chat` (Hinglish/English, alcohol calorie tracking, meal recs).
- Social feed `/api/feed` (posts + stories) from food DB with stock imagery.
- Calorie logging `/api/logs` (auth) — add/list/delete + daily totals.
- Frontend: 3D neon hero (MacroScene break-down), particle field, stories tray (GenZ tips), feed cards (double-tap like, bookmark, log), Food Inspector 3D dialog, floating Coach chat, Diet Plan sheet, My Logs sheet, auth pages.
- Tested: backend 14/14 pass; frontend end-to-end ~95% (no blocking issues).

## Personas
- **Health-conscious young adult (India)** tracking macros socially.
- **Coach/admin** sharing tips and meal inspiration.

## Backlog (prioritized)
- P1: Unified sheet-manager to avoid race when opening a slide-in sheet immediately after closing another.
- P1: Persist likes/bookmarks per user; comments on posts.
- P2: Save generated diet plans to profile + history charts (recharts) for logged calories.
- P2: Swap-meal endpoint (`/api/swap`) to rebalance a meal item.
- P2: Switch CORS to explicit origin list; consider httpOnly cookie auth for production.

## Next Tasks
- Gather user feedback on the neon theme + 3D interaction feel; iterate polish.
