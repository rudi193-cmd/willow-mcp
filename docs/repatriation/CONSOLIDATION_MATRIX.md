# willow corpus — consolidation decision matrix

Generated 2026-07-18 from `willow_compose` (cbm MinHash over 24 repos, 28,825 pieces).
Non-test cross-repo component clusters. Canonical = highest-priority repo holding a copy (hub → fleet → charter → apps).

## Summary
| REVIEW | 162 | 406 |
| FOLD→mcp | 72 | 184 |
| STANDALONE-LIB | 54 | 166 |
| APP-LOCAL | 1 | 4 |

## STANDALONE-LIB candidates (extract a package)
| component | repos | versions | spread |
|---|---|---|---|
 |  get_connection | 4 | 10 | safe-app-store+safe-app-willow-grove+willow+willow-2.0 |
 |  list_channels | 3 | 26 | safe-app-store+safe-app-willow-grove+willow-2.0 |
 |  create_channel | 3 | 15 | safe-app-store+safe-app-willow-grove+willow-2.0 |
 |  safe_addstr | 3 | 3 | safe-app-willow-grove+safe-design+willow-2.0 |
 |  draw_rounded_box | 3 | 3 | safe-app-willow-grove+safe-design+willow-2.0 |
 |  get_channels | 2 | 6 | safe-app-willow-grove+willow-2.0 |
 |  grove_reply | 2 | 4 | safe-app-willow-grove+willow-2.0 |
 |  grove_messages_bus_addressed_to | 2 | 4 | safe-app-willow-grove+willow-2.0 |
 |  _query_ollama_models | 2 | 3 | safe-app-willow-grove+willow-2.0 |
 |  ensure_card_builder_channel | 2 | 3 | safe-app-willow-grove+willow-2.0 |
 |  _msgs_to_dicts | 2 | 3 | safe-app-willow-grove+willow-2.0 |
 |  grove_flag | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  grove_unflag | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  grove_inbox | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  grove_approve | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  _watch_serve_supervisor | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  _get_pool | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  listen_connection | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  init_schema | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  get_channel | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  set_flag | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  get_flags | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  cursor_load | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  load_token | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  main | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  init_pairs | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  desk_mention_handles | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  dashboard_grove_sender | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  merge_attention_messages | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  grove_inbox_bundle | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  grove_agents | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  grove_latest_message_for_sender | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  grove_agent_fleet_rows | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  coordinator_heartbeat | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  grove_channels | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  grove_messages | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  grove_messages_all_agents | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  _ensure_mention_index | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  grove_mentions_for_handles | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  routing_decisions | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  pg_notify_thread | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  __init__ | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  _pg_ok | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  xterm256 | 2 | 2 | safe-app-willow-grove+safe-design |
 |  _kart_ok | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  grove_list_channels | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  main | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  grove_get_history | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  grove_search | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  grove_get_identity | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  grove_channel_resource | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  _on_subscribe | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  grove_watch_all | 2 | 2 | safe-app-willow-grove+willow-2.0 |
 |  grove_get_thread | 2 | 2 | safe-app-willow-grove+willow-2.0 |

## FOLD → willow-mcp (already in hub; dedupe others to import)
| component | repos | versions |
|---|---|---|
 |  file_hash | 4 | 6 |
 |  _unique_dest | 2 | 6 |
 |  exchange_authorization_code | 3 | 6 |
 |  _read_registry | 2 | 5 |
 |  load_refresh_token | 3 | 5 |
 |  cosine | 4 | 5 |
 |  _resolve | 2 | 4 |
 |  available | 2 | 4 |
 |  installed_models | 2 | 4 |
 |  _ocr_image | 3 | 3 |
 |  get | 2 | 3 |
 |  all | 2 | 3 |
 |  _extract_docx | 3 | 3 |
 |  _extract_pdf | 3 | 3 |
 |  default_vault | 3 | 3 |
 |  add_source | 3 | 3 |
 |  add_fragment | 3 | 3 |
 |  stats | 3 | 3 |
 |  init | 3 | 3 |
 |  read | 3 | 3 |
 |  issue_code | 3 | 3 |
 |  load_authorization_code | 3 | 3 |
 |  _embed | 2 | 2 |
 |  centroid | 2 | 2 |
 |  load_rules | 2 | 2 |
 |  should_ignore | 2 | 2 |
 |  classify | 2 | 2 |
 |  set_task_completed_at | 2 | 2 |
 |  learned_hash | 2 | 2 |
 |  merge_learned | 2 | 2 |
 |  build_adaptive_centroids | 2 | 2 |
 |  _slug | 2 | 2 |
 |  _kmeans | 2 | 2 |
 |  discover | 2 | 2 |
 |  promote_clusters | 2 | 2 |
 |  escalation_score | 2 | 2 |
 |  _get_nested | 2 | 2 |
 |  _owner | 2 | 2 |
 |  build_bridge | 2 | 2 |
 |  write_manifest | 2 | 2 |
 |  run | 2 | 2 |
 |  _db_label_counts | 2 | 2 |
 |  list_categories | 2 | 2 |
 |  _relabel_fragments | 2 | 2 |
 |  rename_category | 2 | 2 |
 |  prune_category | 2 | 2 |
 |  __init__ | 2 | 2 |
 |  sink_for | 2 | 2 |
 |  _conn | 2 | 2 |
 |  build_centroids | 2 | 2 |
 |  scan | 2 | 2 |
 |  margin_stats | 2 | 2 |
 |  _http_json | 2 | 2 |
 |  _coerce_verdict | 2 | 2 |
 |  classify_text | 2 | 2 |
 |  describe_image | 2 | 2 |
 |  find_secrets | 2 | 2 |
 |  _track_for_dest | 2 | 2 |
 |  _record_correction | 2 | 2 |
 |  _read_manifest_json | 2 | 2 |
 |  log | 2 | 2 |
 |  main | 2 | 2 |
 |  _plausible_date | 2 | 2 |
 |  _titled_person_fragments | 2 | 2 |
 |  classify | 2 | 2 |
 |  _classify_core | 2 | 2 |
 |  _classify_text_tiers | 2 | 2 |
 |  _classify_regex | 2 | 2 |
 |  build_digest | 2 | 2 |
 |  friction_score | 2 | 2 |
 |  _payload | 2 | 2 |
 |  _post | 2 | 2 |

## REVIEW (decide fold vs standalone) — top 40 by spread
| component | repos | versions | canonical |
|---|---|---|---|
 |  get_character | 3 | 3 | willow:game_engine.py:317-330 |
 |  search_core | 2 | 40 | willow-2.0:core/jeles_sources.py:326-349 |
 |  read_doc | 2 | 9 | willow:apps/opauth/providers/google_docs.py:24-33 |
 |  _resolve_host | 2 | 7 | willow:tools/migrate_kart_sqlite.py:35-46 |
 |  _log_delivery | 2 | 7 | willow-2.0:sap/core/deliver.py:27-38 |
 |  search_dpla | 2 | 6 | willow-2.0:core/jeles_sources.py:1021-1047 |
 |  audit_log | 2 | 6 | willow-2.0:core/willow_store.py:550-558 |
 |  compose | 2 | 5 | willow-2.0:apps/ledger/app.py:249-264 |
 |  _make_request | 2 | 4 | willow:apps/opauth/providers/google.py:100-120 |
 |  handle_callback | 2 | 4 | willow:apps/opauth/providers/google.py:59-73 |
 |  _get_pg_pool | 2 | 4 | willow:core/db.py:20-33 |
 |  list_drive_files | 2 | 4 | willow:apps/opauth/providers/google.py:124-138 |
 |  get_auth_url | 2 | 4 | willow:apps/opauth/providers/google.py:44-57 |
 |  search_gallica | 2 | 4 | willow-2.0:core/jeles_sources.py:802-838 |
 |  _sqlite_to_pg | 2 | 3 | willow:core/db.py:51-71 |
 |  _exec_7 | 2 | 3 | willow-2.0:shoot.py:470-482 |
 |  read_bridge | 2 | 3 | willow-2.0:willow/fylgja/cross_runtime.py:67-74 |
 |  _rm_rf_targets | 2 | 2 | willow-2.0:willow/fylgja/safety/security_scan.py:117-125 |
 |  _check | 2 | 2 | willow-2.0:willow/fylgja/safety/security_scan.py:50-60 |
 |  run_shell_task | 2 | 2 | willow-2.0:core/kart_execute.py:142-235 |
 |  worker_mode | 2 | 2 | willow-2.0:core/kart_lanes.py:28-40 |
 |  collect_bind_mounts | 2 | 2 | willow-2.0:core/kart_sandbox.py:150-222 |
 |  _discover_worktree_targets | 2 | 2 | willow-2.0:core/kart_sandbox.py:108-147 |
 |  check_kart_task | 2 | 2 | willow-2.0:core/kart_task_scan.py:192-214 |
 |  collect_mcp_trust_ro_overlays | 2 | 2 | willow-2.0:core/kart_sandbox.py:225-251 |
 |  collect_config_symlinks | 2 | 2 | willow-2.0:core/kart_sandbox.py:254-283 |
 |  build_bwrap_argv | 2 | 2 | willow-2.0:core/kart_sandbox.py:286-431 |
 |  parse_task_network | 2 | 2 | willow-2.0:core/kart_sandbox.py:450-456 |
 |  _parse_fleet_env_file | 2 | 2 | willow-2.0:core/kart_sandbox.py:459-479 |
 |  kart_env | 2 | 2 | willow-2.0:core/kart_sandbox.py:482-591 |
 |  _run_one_shell | 2 | 2 | willow-2.0:core/kart_execute.py:121-139 |
 |  trim_task_result | 2 | 2 | willow-2.0:core/kart_execute.py:62-74 |
 |  _template_ctx | 2 | 2 | willow-2.0:core/kart_sandbox.py:76-87 |
 |  willow_repo_root | 2 | 2 | willow-2.0:core/kart_sandbox.py:59-73 |
 |  _issue_payload | 2 | 2 | willow-2.0:core/kart_task_scan.py:142-154 |
 |  scan_output | 2 | 2 | willow-2.0:willow/fylgja/safety/security_scan.py:319-327 |
 |  venv_candidates | 2 | 2 | willow-2.0:willow/fylgja/python_env.py:19-45 |
 |  scan_write | 2 | 2 | willow-2.0:willow/fylgja/safety/security_scan.py:308-316 |
 |  _expand_shell_body | 2 | 2 | willow-2.0:core/kart_task_scan.py:132-139 |
 |  _iter_fenced_blocks | 2 | 2 | willow-2.0:core/kart_execute.py:101-118 |
