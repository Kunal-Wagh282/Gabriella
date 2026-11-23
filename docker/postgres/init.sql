-- Runs once when the Postgres volume is first created.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE DATABASE gabriella_test;
\connect gabriella_test
CREATE EXTENSION IF NOT EXISTS vector;
