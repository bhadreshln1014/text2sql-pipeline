"""Quick schema discovery for GA4 event_params."""
import json
import snowflake.connector

creds = json.load(open(r"e:/Spider2/bhadresh/snowflake_credential.json"))
conn = snowflake.connector.connect(database="GA4", **creds)
cur = conn.cursor()

# Check what event_params keys exist related to engagement
cur.execute("""
SELECT DISTINCT ep.value:key::STRING as param_key
FROM GA4.GA4_OBFUSCATED_SAMPLE_ECOMMERCE.EVENTS_20210107,
     LATERAL FLATTEN(input => "EVENT_PARAMS") ep
WHERE ep.value:key::STRING ILIKE '%engage%'
LIMIT 20
""")
print("=== engagement-related event_params keys ===")
for row in cur.fetchall():
    print(f"  {row[0]}")

# Show sample row with engagement param
cur.execute("""
SELECT "USER_PSEUDO_ID",
       ep.value:key::STRING as key,
       ep.value:value:int_value::INT as int_val
FROM GA4.GA4_OBFUSCATED_SAMPLE_ECOMMERCE.EVENTS_20210107,
     LATERAL FLATTEN(input => "EVENT_PARAMS") ep
WHERE ep.value:key::STRING ILIKE '%engage%'
LIMIT 5
""")
print("\n=== sample engagement data ===")
for row in cur.fetchall():
    print(f"  user={row[0]}, key={row[1]}, value={row[2]}")

cur.close()
conn.close()
