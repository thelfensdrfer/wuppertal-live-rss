CREATE TABLE IF NOT EXISTS events
(
    "id"       VARCHAR(255) PRIMARY KEY,
    "title"    VARCHAR(255) NULL,
    "date"     DATE         NULL,
    "start"    VARCHAR(255) NULL,
    "end"      VARCHAR(255) NULL,
    "location" VARCHAR(255) NULL,
    "foto"     VARCHAR(255) NULL
);
