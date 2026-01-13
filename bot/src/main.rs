//! Discord bot for orchestrating Claude Code instances.

mod client;
mod commands;
mod config;

use anyhow::Result;
use serenity::all::{
    Client, Context, EventHandler, GatewayIntents, Interaction, Ready,
};
use serenity::async_trait;
use tracing::{error, info};

use client::WrapperClient;
use config::Config;

/// Bot event handler.
struct Handler {
    wrapper: WrapperClient,
    guild_id: Option<u64>,
}

#[async_trait]
impl EventHandler for Handler {
    async fn ready(&self, ctx: Context, ready: Ready) {
        info!("Bot connected as {}", ready.user.name);
        commands::register_commands(&ctx, &ready, self.guild_id).await;
    }

    async fn interaction_create(&self, ctx: Context, interaction: Interaction) {
        if let Interaction::Command(command) = interaction {
            info!("Received command: {}", command.data.name);

            match command.data.name.as_str() {
                "task" => commands::task(&ctx, &command, &self.wrapper).await,
                "status" => commands::status(&ctx, &command, &self.wrapper).await,
                "approve" => commands::approve(&ctx, &command, &self.wrapper).await,
                "project" => commands::project(&ctx, &command, &self.wrapper).await,
                "register" => commands::handle_register(&ctx, &command, &self.wrapper).await,
                "share" => commands::share(&ctx, &command, &self.wrapper).await,
                _ => {
                    error!("Unknown command: {}", command.data.name);
                }
            }
        }
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    // Load configuration
    let config = Config::from_env()?;

    // Initialize logging
    tracing_subscriber::fmt()
        .with_env_filter(&config.log_level)
        .init();

    info!("Starting Discord bot...");
    info!("Wrapper URL: {}", config.wrapper_url);

    // Create wrapper client
    let wrapper = WrapperClient::new(&config.wrapper_url);

    // Check wrapper health (optional, non-blocking)
    match wrapper.health_check().await {
        Ok(health) => info!("Wrapper service healthy: v{}", health.version),
        Err(e) => error!("Wrapper service not available: {} (bot will retry on commands)", e),
    }

    // Create Discord client
    let handler = Handler {
        wrapper,
        guild_id: config.guild_id,
    };

    let intents = GatewayIntents::empty();
    let mut client = Client::builder(&config.discord_token, intents)
        .event_handler(handler)
        .await?;

    // Run the bot
    info!("Connecting to Discord...");
    client.start().await?;

    Ok(())
}
