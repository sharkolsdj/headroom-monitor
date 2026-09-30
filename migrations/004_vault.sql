-- 004: vault schema — encrypted identity map
-- Encrypted with pgp_sym_encrypt using HM_VAULT_KEY from .env (never stored here)
CREATE TABLE IF NOT EXISTS vault.identity_map (
    code             TEXT  PRIMARY KEY,
    display_name_enc BYTEA,
    iban_enc         BYTEA
);
