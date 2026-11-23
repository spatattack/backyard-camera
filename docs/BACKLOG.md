# Phase 1 audit and follow-on backlog

## Current state and owner actions

The repository has an offline-first Python capture queue, a labelled Mac mock path, Supabase migrations, and a public Next.js archive deployed on Vercel. The earlier upload proof in [STATUS.md](STATUS.md) is historical: the fresh audit found that [the public site](https://backyard-camera.vercel.app) is reachable but reports the archive unavailable, and the documented Supabase project hostname no longer resolves. A fresh upload to production and real Pi operation still need to be verified.

1. **Supabase access:** Check the [documented Backyard Camera project](https://supabase.com/dashboard/project/ucibqecfqzjnvhdxiura). Restore it if possible; if replacement is necessary, review the plan/cost first. Verify both migrations and provision a dedicated, confirmed device account. Set the device credentials locally on Mac/Pi, not in Git or chat. See [Cloud configuration](CLOUD.md).
2. **Vercel access:** Check that Production (and Preview if used) has the active project's `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY`; redeploy if changed. Run the mock upload, confirm the matching row and public JPEG, then verify an open latest archive updates without a reload.
3. **Hardware access:** Install and test the Pi/Cam Module 3 combination, including autofocus, five-minute daylight timing, reboot and Wi-Fi recovery, and mounting/power/weatherproofing. Follow the [hardware acceptance run](HARDWARE.md).

## Phase 2 — Photography intelligence

[Cloud labelling](LABELLING.md) now covers basic animal, vehicle and person detection and false motion-trigger filtering. The photography scoring and owner review workflow below remain follow-up work.

1. **Filter and score candidates in the cloud.** Reject corrupt images and failed exposures; score composition, lighting, atmosphere, visual interest and novelty against the usual view. Validate against real examples and track cost before enabling it unattended.
2. **Build the daily review loop.** Preserve approximately ten strong candidates per day, shortlist five, and let the owner select a winner or override the recommendation. Record selections and feedback; refine ranking before enabling autonomous publication.
3. **Enrich the useful subset.** Collect timestamps, available exposure data and scores. Generate short descriptions and identify notable scene changes, weather, animals and people without identifying individuals. Explore private visitor recognition only after explicit privacy safeguards and review.

## Phase 3 — Public website and private operations

1. **Publish the daily photograph.** Give the day's winner a prominent spot in a minimal, editorial, photography-first layout, with an About page explaining the equipment, experiment and selection process.
2. **Build the year-long archive.** Add chronological galleries, calendar navigation to each day's winner, and photo details with timestamp, description and relevant metadata.
3. **Add a private admin dashboard.** Gate access to candidate review, winner selection, device health and capture history. Keep private operational and candidate data out of the public site.
