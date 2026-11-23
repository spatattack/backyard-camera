# Cloud capture labelling

GitHub Actions runs the labeller about every ten minutes, or manually via **Actions → Label captures → Run workflow**. It processes at most 32 unlabelled captures per run, including scheduled and mock captures. Failed downloads or inferences retry up to three times; remaining unlabelled photos stay visible. It records the label, score, model version and visibility in Supabase. No AI runs on the Pi.

The worker uses the Apache-2.0 [OWL-V2 Base detector](https://huggingface.co/google/owlv2-base-patch16-ensemble) on the runner's CPU. One open-vocabulary detector covers the garden species without a second model; the public weights are pinned and cached. Images are downloaded from Supabase to the GitHub runner only and are not uploaded to the model provider or cached. There is no AI account or API fee; compute is £0 on standard runners for a public repository. Reads still use the existing Supabase egress quota.

## Enable

1. Apply `20261008160000_capture_labels.sql` after the two existing migrations. The site can still read the earlier schema during rollout. Update the device uploader to this release so it can verify duplicate uploads that are already hidden; its normal capture and upload path is unchanged.
2. In [repository Actions secrets](https://github.com/spatattack/backyard-camera/settings/secrets/actions), add `SUPABASE_URL` for the Backyard project and `SUPABASE_SECRET_KEY` for that project's server-side secret key. Never put the key on the Pi, in Vercel, or in Git.
3. Merge to the default branch, run **Label captures** manually and check its run log. To retry a permanently failed image after fixing the cause, reset its `label_attempts` to zero in the SQL editor. To release a reviewed capture into the archive, set its `label_visibility` to `visible`; review the image before doing so.

GitHub automatically disables scheduled workflows in public repositories after 60 days without repository activity. While the workflow is disabled, new captures stay unlabelled and visible. To resume, go to **Actions → Label captures → Enable workflow**, or run `gh workflow enable label-captures.yml` from the repository. Scheduled runs will then drain the backlog automatically.

To test on local files without using any Supabase credentials:

```sh
python -m pip install -r cloud/requirements.txt
python cloud/labeller.py --dry-run /path/to/*.jpg
```

## Visibility and privacy

- A person detection takes priority over other subjects and hides the row pending owner review. A motion capture without a detection is hidden as a likely false trigger; a scheduled capture without a detection stays visible. Scores are model scores, not calibrated probabilities. A detection can be wrong or miss a small or obscured subject.
- Unlabelled photos are visible to keep the archive usable during outages. A new photo with a person can appear until it is processed: typically one run interval, but queue backlog, skipped runs, inference failures and missed detections can leave it visible longer.
- Hidden rows are excluded by database access rules, **not** by private storage. The JPEG bucket remains public: the random UUID object paths are hard to guess and are not logged by the worker, but a direct URL already known, shared or cached still works. To prevent access to an individual JPEG, remove the object; for strict privacy, use a private bucket with pre-publication review instead. Aim the camera away from areas where people expect privacy.
