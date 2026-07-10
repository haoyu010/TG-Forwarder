# Product

## Register

product

## Users

Operators who run private Telegram media forwarding channels. They need to monitor source channels, classify posts through TMDB, filter unwanted genres, and confirm that forwarding is working without reading container logs all day.

## Product Purpose

This product listens to configured Telegram source channels with a user account, enriches media posts with TMDB metadata, filters blacklisted organizer-style categories and TMDB genres, and forwards approved posts to one target channel with a clear metadata header. Success means the operator can deploy it with Docker, see current health in a web dashboard, and understand every forwarded, filtered, or failed message.

## Brand Personality

Precise, calm, operational.

## Anti-references

It should not look like a marketing landing page, a decorative media app, or an over-animated analytics demo. The dashboard should avoid large hero sections, ornamental cards, emoji icons, and vague status labels.

## Design Principles

- Make the forwarding pipeline inspectable from source message to final action.
- Prefer dense but readable operational views over decorative layouts.
- Use explicit states for connected, filtered, forwarded, failed, and pending work.
- Keep configuration reversible and easy to audit.
- Treat accessibility as part of operator reliability, not polish.

## Accessibility & Inclusion

Target WCAG AA contrast. All interactive controls need keyboard focus states, visible labels, and non-color status text. Motion should be minimal and respect reduced-motion settings.
