WITH yes_choice AS (
    SELECT
        d.device_id,
        i.variant,
        r.review_id,
        i.image_id,
        i.path,
        d.final_result,
        d.final_decision_source_image_id,
        ROW_NUMBER() OVER (
            PARTITION BY d.device_id
            ORDER BY r.decided_at, r.review_id
        ) AS rn
    FROM devices AS d
    JOIN images AS i
      ON i.image_id = CAST(d.final_decision_source_image_id AS INTEGER)
    LEFT JOIN reviews AS r
      ON r.image_id = i.image_id
     AND r.result IN ('yes', 'auto_skip_device_yes')
    WHERE d.final_result = 'yes'
),
no_choice AS (
    SELECT
        d.device_id,
        i.variant,
        r.review_id,
        i.image_id,
        i.path,
        d.final_result,
        d.final_decision_source_image_id,
        ROW_NUMBER() OVER (
            PARTITION BY d.device_id
            ORDER BY r.decided_at, r.review_id
        ) AS rn
    FROM devices AS d
    JOIN images AS i
      ON i.device_id = d.device_id
    JOIN reviews AS r
      ON r.image_id = i.image_id
    WHERE d.final_result = 'no'
      AND r.result = 'no'          -- only devices with explicit "no" reviews
),
skip_choice AS (
    SELECT
        d.device_id,
        i.variant,
        r.review_id,
        i.image_id,
        i.path,
        d.final_result,
        "skip" AS final_decision_source_image_id,   -- override to NULL as requested
        ROW_NUMBER() OVER (
            PARTITION BY d.device_id
            ORDER BY r.decided_at, r.review_id    -- "first" review for that device
        ) AS rn
    FROM devices AS d
    JOIN images AS i
      ON i.device_id = d.device_id
    JOIN reviews AS r
      ON r.image_id = i.image_id
    WHERE d.final_result = 'no'
      AND r.result = 'skip'        -- use skip reviews
      AND NOT EXISTS (             -- only devices with *no* 'no' reviews
          SELECT 1
          FROM images i2
          JOIN reviews r2
            ON r2.image_id = i2.image_id
          WHERE i2.device_id = d.device_id
            AND r2.result = 'no'
      )
)
SELECT
    device_id,
    variant,
    review_id,
    image_id,
    path,
    final_result,
    final_decision_source_image_id,
	h.*
FROM yes_choice
LEFT JOIN dhr_rows AS h ON yes_choice.device_id = h.id_no
WHERE rn = 1

UNION ALL

SELECT
    device_id,
    variant,
    review_id,
    image_id,
    path,
    final_result,
    final_decision_source_image_id,
	h.*
FROM no_choice
LEFT JOIN dhr_rows AS h ON no_choice.device_id = h.id_no
WHERE rn = 1

UNION ALL

SELECT
    device_id,
    variant,
    review_id,
    image_id,
    path,
    final_result,
    final_decision_source_image_id,
	h.*
FROM skip_choice
LEFT JOIN dhr_rows AS h ON skip_choice.device_id = h.id_no
WHERE rn = 1

ORDER BY image_id;
