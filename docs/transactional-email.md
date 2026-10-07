# Transactional email

Rowset's Django/allauth emails (signup confirmation, confirmation resend,
password reset and existing-account notices) share Django's configured mail backend.
Production uses Anymail's Mailgun backend and `mg.rowset.app`, with the visible
sender `Rowset <rasul@rowset.app>`. Error mail uses `Rowset Errors <rasul@rowset.app>`.
No newsletter, Listmonk instance or receiving mailbox is provisioned by this setup.
Existing optional Buttondown integration is unchanged.

## Configuration

Set `MAILGUN_API_KEY` to a domain-scoped sending key and
`MAILGUN_SENDER_DOMAIN` to your verified Mailgun domain on **both web and workers**.
`DEFAULT_FROM_EMAIL` and `SERVER_EMAIL` can override the branded defaults.
Production credentials are stored in Infisical, Openclaw/prod, `/projects/rowset`.
Never place keys in Git or logs. Local development uses Mailhog; an empty key
outside local development uses the console backend, not actual delivery.

DNS includes Mailgun's SPF, 2048-bit DKIM, MX and unproxied tracking CNAME records.
Monitor-only DMARC with relaxed alignment allows the root-domain From address
and subdomain authentication. Open/click/unsubscribe tracking is disabled for
transactional mail. MX records on the sending subdomain do not create an inbox
at the visible From address.

## Verify or roll back

Check Mailgun reports the domain active and every required record valid before
switching. Verify deployed backend, sender and domain in both web and workers;
send only to an operator-controlled inbox and check SPF, DKIM and DMARC results.
Exercise confirmation and password-reset rendering/delivery via the account adapter.
Do not bulk-resend customer messages as a smoke test.

For rollback, restore the saved pre-change Mailgun key and set
`MAILGUN_SENDER_DOMAIN=mg.lvtd.dev`,
`DEFAULT_FROM_EMAIL=Rasul Kireev <rasul@lvtd.dev>` and
`SERVER_EMAIL=Rowset Errors <rasul@lvtd.dev>` together on each service.
The prior domain and all unrelated DNS are retained. No database migration or
change to optional email verification is required.
