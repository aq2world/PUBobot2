CREATE USER IF NOT EXISTS 'pubobot'@'%' IDENTIFIED WITH caching_sha2_password BY 'generate_your_own';
CREATE DATABASE IF NOT EXISTS pubodb CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci ;
GRANT ALL PRIVILEGES ON pubodb.* TO 'pubobot'@'%';