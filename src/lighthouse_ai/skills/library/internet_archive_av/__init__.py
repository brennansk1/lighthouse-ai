"""Internet Archive audio/video collections skill — SL10.

Searches and retrieves audio/video items from archive.org's publicly accessible
collections (public-domain films, CC recordings, archived radio and TV, the
Television News Archive).  Distinct from the Wayback skill (web snapshots) —
this skill targets the media catalogue via the Internet Archive's advancedsearch
and metadata APIs.

All network access goes through SkillContext primitives; the import guard
enforces that this package never touches httpx/requests/urllib directly.
"""
