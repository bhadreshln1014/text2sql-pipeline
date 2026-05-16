WITH
-- Calculate incoming and outgoing transfers for each address
transfers AS (
    SELECT
        t."from_address" AS address,
        -SUM(t."value") AS balance
    FROM
        ETHEREUM_BLOCKCHAIN.ETHEREUM_BLOCKCHAIN.TRACES t
    WHERE
        t."status" = 1
        AND t."call_type" NOT IN ('delegatecall', 'callcode', 'staticcall')
        AND t."from_address" IS NOT NULL
    GROUP BY
        t."from_address"

    UNION ALL

    SELECT
        t."to_address" AS address,
        SUM(t."value") AS balance
    FROM
        ETHEREUM_BLOCKCHAIN.ETHEREUM_BLOCKCHAIN.TRACES t
    WHERE
        t."status" = 1
        AND t."call_type" NOT IN ('delegatecall', 'callcode', 'staticcall')
        AND t."to_address" IS NOT NULL
    GROUP BY
        t."to_address"
),

-- Calculate miner rewards
miner_rewards AS (
    SELECT
        b."miner" AS address,
        SUM(t."gas_used" * (SELECT AVG(tx."gas_price") FROM ETHEREUM_BLOCKCHAIN.ETHEREUM_BLOCKCHAIN.TRANSACTIONS tx WHERE tx."block_number" = b."number")) AS balance
    FROM
        ETHEREUM_BLOCKCHAIN.ETHEREUM_BLOCKCHAIN.BLOCKS b
    JOIN
        ETHEREUM_BLOCKCHAIN.ETHEREUM_BLOCKCHAIN.TRACES t ON b."number" = t."block_number"
    GROUP BY
        b."miner"
),

-- Calculate sender gas fee deductions
sender_gas_fees AS (
    SELECT
        tx."from_address" AS address,
        -SUM(tx."receipt_gas_used" * tx."gas_price") AS balance
    FROM
        ETHEREUM_BLOCKCHAIN.ETHEREUM_BLOCKCHAIN.TRANSACTIONS tx
    WHERE
        tx."receipt_status" = 1
        AND tx."from_address" IS NOT NULL
    GROUP BY
        tx."from_address"
),

-- Combine all balance components
combined_balances AS (
    SELECT
        address,
        SUM(balance) AS net_balance
    FROM
        transfers
    GROUP BY
        address

    UNION ALL

    SELECT
        address,
        SUM(balance) AS net_balance
    FROM
        miner_rewards
    GROUP BY
        address

    UNION ALL

    SELECT
        address,
        SUM(balance) AS net_balance
    FROM
        sender_gas_fees
    GROUP BY
        address
),

-- Calculate total net balance for each address
net_balances AS (
    SELECT
        address,
        SUM(net_balance) AS total_net_balance
    FROM
        combined_balances
    GROUP BY
        address
),

-- Identify top 10 addresses by net balance
top_addresses AS (
    SELECT
        address,
        total_net_balance
    FROM
        net_balances
    ORDER BY
        total_net_balance DESC
    LIMIT 10
)

-- Calculate the average balance of the top 10 addresses
SELECT
    ROUND(AVG(total_net_balance) / POWER(10, 15), 2) AS average_balance_in_quadrillions
FROM
    top_addresses;