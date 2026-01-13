//! Configuration management for the Discord bot.

use anyhow::{Context, Result};
use std::env;

/// Application configuration loaded from environment variables.
#[derive(Debug, Clone)]
pub struct Config {
    /// Discord bot token
    pub discord_token: String,

    /// Discord guild ID for registering slash commands
    pub guild_id: Option<u64>,

    /// Wrapper service URL
    pub wrapper_url: String,

    /// Log level
    pub log_level: String,
}

impl Config {
    /// Load configuration from environment variables.
    pub fn from_env() -> Result<Self> {
        dotenvy::dotenv().ok();

        let discord_token = env::var("DISCORD_TOKEN")
            .context("DISCORD_TOKEN environment variable not set")?;

        let guild_id = env::var("DISCORD_GUILD_ID")
            .ok()
            .and_then(|s| s.parse().ok());

        let wrapper_url = env::var("WRAPPER_URL")
            .unwrap_or_else(|_| "http://localhost:8000".to_string());

        let log_level = env::var("RUST_LOG")
            .unwrap_or_else(|_| "info".to_string());

        Ok(Self {
            discord_token,
            guild_id,
            wrapper_url,
            log_level,
        })
    }
}
