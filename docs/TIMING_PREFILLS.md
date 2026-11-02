# Timestamp-supported Nature of Use suggestions

These rules prepare editable fields; they never confirm reuse, timestamps,
instruments, lyrics or a review. They use the union of intervals so overlapping
model windows are not counted twice. The recording and replay paths stay separate.

| Timing evidence | Suggested fields | Required listening check |
| --- | --- | --- |
| Span at least 85% of the track and either at least 60% covered, or at least six appearances with no gap over 18% of track length | Throughout; whole track | Confirm that this is musically throughout, not unrelated sound overlap |
| All appearances in the opening 20% | Intro only | Check the intro boundary |
| All appearances in the final 20% | Outro only | Check the outro boundary |
| Appearances confined to both opening and ending 20% | Intro/outro outside chorus | Check section names and absence elsewhere |
| Repeated short, similarly sized intervals | A short repeating loop | Check that these intervals really form a loop |
| One interior appearance | One appearance | Identify the musical section |
| Multiple interior appearances | Recurs in multiple passages | Choose verse, chorus or another section; timestamps alone cannot decide |
| Sample intervals fully overlap named ranges in the optional song-section map | Actual mapped sections; corresponding placement where supported | Verify the map and placement |

A section map only supports an exclusive placement (for example chorus only) if
its named ranges cover every sample occurrence. An incomplete map may suggest
known overlapping sections but does not assert an exclusive placement. Intro,
outro, bridge-only and selected-sections classes extend the earlier six placement choices without
changing the earlier values. Bridge-only and verse/chorus labels require a
section map or creator selection, not a location-based guess.

Reuse method is seeded from the recording/replay path. Sound identity, lyrics,
role, pitch and verification are not fabricated. User edits take precedence;
stale unconfirmed automatic defaults are cleared when timing patterns change.
Editing timestamps invalidates their listening confirmation and the details
check. Invalid intervals do not crash suggestion generation and still block the
final review.
