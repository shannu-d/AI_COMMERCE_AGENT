-- Runs once, on first initialisation of the PostgreSQL container.
--
-- Creates the throwaway database the test suite uses, so TEST_DATABASE_URL from
-- .env.example works without a manual step. The schema tests create and drop
-- tables, which is why they must never point at the development database.
CREATE DATABASE ai_commerce_test OWNER ai_commerce;
