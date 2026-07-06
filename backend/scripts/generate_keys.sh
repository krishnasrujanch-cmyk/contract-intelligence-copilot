#!/usr/bin/env bash
# =============================================================================
# Generate RSA-2048 key pair for JWT RS256 signing
# Run ONCE before first deployment: ./scripts/generate_keys.sh
# =============================================================================
set -euo pipefail

KEYS_DIR="$(dirname "$0")/../keys"
mkdir -p "$KEYS_DIR"

PRIVATE_KEY="$KEYS_DIR/private.pem"
PUBLIC_KEY="$KEYS_DIR/public.pem"

if [[ -f "$PRIVATE_KEY" ]]; then
    echo "⚠️  Private key already exists at $PRIVATE_KEY"
    echo "    Delete it manually if you want to regenerate (this invalidates all existing tokens)."
    exit 0
fi

echo "🔑 Generating RSA-2048 private key..."
openssl genrsa -out "$PRIVATE_KEY" 2048

echo "🔑 Extracting public key..."
openssl rsa -in "$PRIVATE_KEY" -pubout -out "$PUBLIC_KEY"

# Restrict permissions — private key should be readable only by owner
chmod 600 "$PRIVATE_KEY"
chmod 644 "$PUBLIC_KEY"

echo "✅ Keys generated:"
echo "   Private: $PRIVATE_KEY (permissions: 600)"
echo "   Public:  $PUBLIC_KEY (permissions: 644)"
echo ""
echo "⚠️  Add keys/ to .gitignore — NEVER commit private.pem to version control"
