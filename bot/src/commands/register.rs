//! /register command - Register local wrapper or manage user settings.

use serenity::all::{
    CommandInteraction, CommandOptionType, Context, CreateCommand, CreateCommandOption,
    CreateInteractionResponse, CreateInteractionResponseMessage,
};
use tracing::{error, info};

use crate::client::{ExecutionMode, RegisterLocalRequest, WrapperClient};

/// Create the command registration.
pub fn register() -> CreateCommand {
    CreateCommand::new("register")
        .description("Register your local wrapper or manage settings")
        .add_option(
            CreateCommandOption::new(
                CommandOptionType::SubCommand,
                "local",
                "Register your local wrapper URL",
            )
            .add_sub_option(
                CreateCommandOption::new(
                    CommandOptionType::String,
                    "url",
                    "Your wrapper URL (e.g., http://your-ip:8000)",
                )
                .required(true),
            ),
        )
        .add_option(
            CreateCommandOption::new(
                CommandOptionType::SubCommand,
                "unregister",
                "Unregister your local wrapper",
            ),
        )
        .add_option(
            CreateCommandOption::new(
                CommandOptionType::SubCommand,
                "mode",
                "Set your default execution mode",
            )
            .add_sub_option(
                CreateCommandOption::new(
                    CommandOptionType::String,
                    "default",
                    "Default mode for tasks",
                )
                .required(true)
                .add_string_choice("Local (your machine)", "local")
                .add_string_choice("Cluster (Pi nodes)", "cluster"),
            ),
        )
        .add_option(
            CreateCommandOption::new(
                CommandOptionType::SubCommand,
                "status",
                "Check your registration status",
            ),
        )
}

/// Handle the /register command.
pub async fn handle_register(ctx: &Context, command: &CommandInteraction, wrapper: &WrapperClient) {
    let subcommand = command
        .data
        .options
        .first()
        .map(|opt| opt.name.as_str())
        .unwrap_or("status");

    let user_id = command.user.id.to_string();
    let user_name = command.user.name.clone();

    info!(
        "Register command received: subcommand='{}', user={}",
        subcommand, user_id
    );

    match subcommand {
        "local" => handle_register_local(ctx, command, wrapper, &user_id, &user_name).await,
        "unregister" => handle_unregister(ctx, command, wrapper, &user_id).await,
        "mode" => handle_set_mode(ctx, command, wrapper, &user_id).await,
        "status" => handle_status(ctx, command, wrapper, &user_id).await,
        _ => {
            let response = CreateInteractionResponseMessage::new()
                .content("Unknown subcommand.")
                .ephemeral(true);
            let _ = command
                .create_response(&ctx.http, CreateInteractionResponse::Message(response))
                .await;
        }
    }
}

async fn handle_register_local(
    ctx: &Context,
    command: &CommandInteraction,
    wrapper: &WrapperClient,
    user_id: &str,
    user_name: &str,
) {
    // Extract URL from subcommand options using pattern matching for Serenity 0.12
    let sub_opts = command
        .data
        .options
        .first()
        .and_then(|opt| {
            if let serenity::all::CommandDataOptionValue::SubCommand(opts) = &opt.value {
                Some(opts.clone())
            } else {
                None
            }
        })
        .unwrap_or_default();

    let url = sub_opts
        .iter()
        .find(|o| o.name == "url")
        .and_then(|o| o.value.as_str())
        .unwrap_or("");

    if url.is_empty() {
        let response = CreateInteractionResponseMessage::new()
            .content("❌ URL is required.")
            .ephemeral(true);
        let _ = command
            .create_response(&ctx.http, CreateInteractionResponse::Message(response))
            .await;
        return;
    }

    let request = RegisterLocalRequest {
        discord_id: user_id.to_string(),
        discord_name: user_name.to_string(),
        wrapper_url: url.to_string(),
        auth_token: None,
    };

    match wrapper.register_local(request).await {
        Ok(user) => {
            let content = format!(
                "✅ **Local Wrapper Registered**\n\n\
                **URL:** `{}`\n\
                **Default Mode:** {}\n\n\
                Now run the wrapper on your machine:\n\
                ```bash\n\
                cd wrapper && uvicorn wrapper.main:app --host 0.0.0.0 --port 8000\n\
                ```\n\n\
                Then use `/task prompt:\"...\" project:my-project` to run tasks!",
                user.local_wrapper_url.unwrap_or_default(),
                user.default_mode,
            );
            let response = CreateInteractionResponseMessage::new()
                .content(content)
                .ephemeral(false);
            if let Err(e) = command
                .create_response(&ctx.http, CreateInteractionResponse::Message(response))
                .await
            {
                error!("Failed to send register response: {}", e);
            }
        }
        Err(e) => {
            error!("Failed to register local wrapper: {}", e);
            let response = CreateInteractionResponseMessage::new()
                .content(format!("❌ Failed to register: {}", e))
                .ephemeral(true);
            let _ = command
                .create_response(&ctx.http, CreateInteractionResponse::Message(response))
                .await;
        }
    }
}

async fn handle_unregister(
    ctx: &Context,
    command: &CommandInteraction,
    wrapper: &WrapperClient,
    user_id: &str,
) {
    match wrapper.unregister_local(user_id).await {
        Ok(()) => {
            let response = CreateInteractionResponseMessage::new()
                .content("✅ Local wrapper unregistered.")
                .ephemeral(false);
            if let Err(e) = command
                .create_response(&ctx.http, CreateInteractionResponse::Message(response))
                .await
            {
                error!("Failed to send unregister response: {}", e);
            }
        }
        Err(e) => {
            error!("Failed to unregister: {}", e);
            let response = CreateInteractionResponseMessage::new()
                .content(format!("❌ Failed to unregister: {}", e))
                .ephemeral(true);
            let _ = command
                .create_response(&ctx.http, CreateInteractionResponse::Message(response))
                .await;
        }
    }
}

async fn handle_set_mode(
    ctx: &Context,
    command: &CommandInteraction,
    wrapper: &WrapperClient,
    user_id: &str,
) {
    // Extract mode from subcommand options using pattern matching for Serenity 0.12
    let sub_opts = command
        .data
        .options
        .first()
        .and_then(|opt| {
            if let serenity::all::CommandDataOptionValue::SubCommand(opts) = &opt.value {
                Some(opts.clone())
            } else {
                None
            }
        })
        .unwrap_or_default();

    let mode_str = sub_opts
        .iter()
        .find(|o| o.name == "default")
        .and_then(|o| o.value.as_str())
        .unwrap_or("local");

    let mode = match mode_str {
        "cluster" => ExecutionMode::Cluster,
        _ => ExecutionMode::Local,
    };

    match wrapper.set_user_mode(user_id, mode).await {
        Ok(user) => {
            let content = format!(
                "✅ Default mode set to **{}**\n\n\
                Your tasks will now run on: {}",
                user.default_mode,
                if user.default_mode == "cluster" {
                    "the Pi cluster"
                } else {
                    "your local machine"
                }
            );
            let response = CreateInteractionResponseMessage::new()
                .content(content)
                .ephemeral(false);
            if let Err(e) = command
                .create_response(&ctx.http, CreateInteractionResponse::Message(response))
                .await
            {
                error!("Failed to send mode response: {}", e);
            }
        }
        Err(e) => {
            error!("Failed to set mode: {}", e);
            let response = CreateInteractionResponseMessage::new()
                .content(format!("❌ Failed to set mode: {}\n\nYou may need to register first with `/register local url:<your-url>`", e))
                .ephemeral(true);
            let _ = command
                .create_response(&ctx.http, CreateInteractionResponse::Message(response))
                .await;
        }
    }
}

async fn handle_status(
    ctx: &Context,
    command: &CommandInteraction,
    wrapper: &WrapperClient,
    user_id: &str,
) {
    match wrapper.get_user(user_id).await {
        Ok(user) => {
            let local_status = user
                .local_wrapper_url
                .as_ref()
                .map(|url| format!("✅ Registered: `{}`", url))
                .unwrap_or_else(|| "❌ Not registered".to_string());

            let cluster_status = if user.cluster_enabled {
                format!(
                    "✅ Enabled (storage: `{}`)",
                    user.cluster_storage_path.unwrap_or_default()
                )
            } else {
                "❌ Not enabled".to_string()
            };

            let content = format!(
                "**Your Registration Status**\n\n\
                **Discord ID:** `{}`\n\
                **Local Wrapper:** {}\n\
                **Cluster Access:** {}\n\
                **Default Mode:** `{}`\n\
                **Last Seen:** {}",
                user.discord_id,
                local_status,
                cluster_status,
                user.default_mode,
                user.last_seen,
            );
            let response = CreateInteractionResponseMessage::new()
                .content(content)
                .ephemeral(true);
            if let Err(e) = command
                .create_response(&ctx.http, CreateInteractionResponse::Message(response))
                .await
            {
                error!("Failed to send status response: {}", e);
            }
        }
        Err(_) => {
            let content = "**Not Registered**\n\n\
                You haven't registered yet.\n\n\
                To use your local machine:\n\
                `/register local url:http://your-ip:8000`\n\n\
                To use the Pi cluster (if enabled by admin):\n\
                Contact an admin to enable cluster access.";
            let response = CreateInteractionResponseMessage::new()
                .content(content)
                .ephemeral(true);
            let _ = command
                .create_response(&ctx.http, CreateInteractionResponse::Message(response))
                .await;
        }
    }
}
