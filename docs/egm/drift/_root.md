## README.md (repo root)

- [undocumented] README.md:89-102 lists the deploy pipeline as seven steps (Validate, approval, migration dry run, backend deploy, frontend deploy, smoke, release record). `.github/workflows/production.yml:1049` (`sentry-release`, `needs: [smoke]`) also runs after smoke, alongside `publish-release` (`production.yml:1119`). It creates the Sentry release and is not mentioned.
