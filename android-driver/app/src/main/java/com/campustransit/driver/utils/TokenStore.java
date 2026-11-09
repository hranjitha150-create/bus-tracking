package com.campustransit.driver.utils;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.time.Instant;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Only authenticated ciphertext is stored in private preferences; keys stay in Keystore. */
public final class TokenStore {
    private static final String ALIAS = "campus_driver_session_v1";
    private static final Object LOCK = new Object();
    private final SharedPreferences prefs;
    public TokenStore(Context context) { prefs = context.getSharedPreferences("secure_session", Context.MODE_PRIVATE); }
    private SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore"); store.load(null);
        if (!store.containsAlias(ALIAS)) {
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setKeySize(256).build());
            generator.generateKey();
        }
        return (SecretKey) store.getKey(ALIAS, null);
    }
    public void save(String token, String expires) throws Exception {
        synchronized (LOCK) {
            JSONObject data = new JSONObject(); data.put("token", token); data.put("expires", expires);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE, key());
            String ciphertext = Base64.encodeToString(cipher.doFinal(data.toString().getBytes(StandardCharsets.UTF_8)), Base64.NO_WRAP);
            if (!prefs.edit().putString("ciphertext", ciphertext).putString("iv", Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP)).commit())
                throw new IllegalStateException("Cannot save secure session");
        }
    }
    public String token() {
        synchronized (LOCK) {
            try {
                String encrypted = prefs.getString("ciphertext", "");
                if (encrypted.isEmpty()) return "";
                Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
                cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, Base64.decode(prefs.getString("iv", ""), Base64.NO_WRAP)));
                JSONObject data = new JSONObject(new String(cipher.doFinal(Base64.decode(encrypted, Base64.NO_WRAP)), StandardCharsets.UTF_8));
                if (!Instant.parse(data.getString("expires")).isAfter(Instant.now())) { clear(); return ""; }
                return data.getString("token");
            } catch (Exception invalidSession) { clear(); return ""; }
        }
    }
    // Logout must reach disk before returning, including an immediate process kill.
    @android.annotation.SuppressLint("ApplySharedPref")
    public void clear() { synchronized (LOCK) { prefs.edit().clear().commit(); } }
}
