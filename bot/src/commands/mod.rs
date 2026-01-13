//! Discord slash commands module.

mod approve;
mod project;
mod register;
mod share;
mod status;
mod task;

pub use approve::approve;
pub use project::project;
pub use register::handle_register;
pub use share::share;
pub use status::status;
pub use task::task;

use serenity::all::{Command, Context, GuildId, Ready};
use tracing::{error, info};

/// Register all slash commands with Discord.
pub async fn register_commands(ctx: &Context, ready: &Ready, guild_id: Option<u64>) {
    info!("Registering slash commands...");

    let commands = vec![
        task::register(),
        status::register(),
        approve::register(),
        project::register(),
        register::register(),
        share::register(),
    ];

    // Register to specific guild (faster) or globally
    if let Some(gid) = guild_id {
        let guild = GuildId::new(gid);
        match guild.set_commands(&ctx.http, commands).await {
            Ok(cmds) => info!("Registered {} guild commands", cmds.len()),
            Err(e) => error!("Failed to register guild commands: {}", e),
        }
    } else {
        match Command::set_global_commands(&ctx.http, commands).await {
            Ok(cmds) => info!("Registered {} global commands", cmds.len()),
            Err(e) => error!("Failed to register global commands: {}", e),
        }
    }

    info!("{} is connected!", ready.user.name);
}
