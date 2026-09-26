-- The only SQL seed: versioned rule policy, never a second copy of demo data.
INSERT INTO rule_threshold
 (rule_id, revision, metric, operator, threshold, unit, actions, fallback_only,
  effective_at, changed_by, reason)
VALUES
 ('credit.R1',1,'credit.icr_p50','lt',1.0,'ratio','["restructure"]',false,
  '2026-09-11 00:00:00','spec:v3','TZ 3.6'),
 ('credit.R2',1,'credit.covenant_breach_probability','ge',0.5,'fraction',
  '["add_collateral","covenant_talks"]',false,'2026-09-11 00:00:00','spec:v3','TZ 3.6'),
 ('credit.R3',1,'credit.delta_pd_p50','ge',5.0,'percentage_point','["limit_cut"]',false,
  '2026-09-11 00:00:00','spec:v3','TZ 3.6'),
 ('credit.R4',1,'credit.rate_fx_channel_share','ge',0.5,'fraction','["hedge"]',false,
  '2026-09-11 00:00:00','spec:v3','TZ 3.6'),
 ('credit.R5',1,'credit.delta_el_p50','gt',0.0,'RUB_million','["watchlist"]',true,
  '2026-09-11 00:00:00','spec:v3','TZ 3.6')
ON CONFLICT (rule_id, revision) DO NOTHING;
