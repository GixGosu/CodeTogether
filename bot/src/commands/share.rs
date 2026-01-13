//! /share command - Manage collaborative wrapper access.

use serenity::all::{
    CommandInteraction, CommandOptionType, Context, CreateCommand, CreateCommandOption,
    CreateInteractionResponse, CreateInteractionResponseMessage,
};
use tracing::{error, info};

use crate::client::WrapperClient;

/// Create the command registration.
pub fn register() -> CreateCommand {
    CreateCommand::new("share")
        .description("Manage who can use your wrapper for collaborative coding")
        .add_option(
            CreateCommandOption::new(
                CommandOptionType::SubCommand,
                "add",
                "Grant another user access to your wrapper",
            )
            .add_sub_option(
                CreateCommandOption::new(
                    CommandOptionType::User,
                    "user",
                    "The user to grant access to",
                )
                .required(true),
            ),
        )
        .add_option(
            CreateCommandOption::new(
                CommandOptionType::SubCommand,
                "remove",
                "Remove a user's access to your wrapper",
            )
            .add_sub_option(
                CreateCommandOption::new(
                    CommandOptionType::User,
                    "user",
                    "The user to remove access from",
                )
                .required(true),
            ),
        )
        .add_option(
            CreateCommandOption::new(
                CommandOptionType::SubCommand,
                "list",
                "List users who have access to your wrapper",
            ),
        )
        .add_option(
            CreateCommandOption::new(
                CommandOptionType::SubCommand,
                "available",
                "List wrappers you have access to (your own + shared with you)",
            ),
        )
}

/// Handle the /share command.
pub async fn share(ctx: &Context, command: &CommandInteraction, wrapper: &WrapperClient) {
    // Get user ID from Discord (server-side, cannot be spoofed)
    let user_id = command.user.id.to_string();

    // Get the subcommand
    let subcommand = command
        .data
        .options
        .first()
        .map(|opt| opt.name.as_str())
        .unwrap_or("list");

    info!(
        "Share command received: subcommand='{}', user={}",
        subcommand, user_id
    );

    match subcommand {
        "add" => handle_add(ctx, command, wrapper, &user_id).await,
        "remove" => handle_remove(ctx, command, wrapper, &user_id).await,
        "list" => handle_list(ctx, command, wrapper, &user_id).await,
        "available" => handle_available(ctx, command, wrapper, &user_id).await,
        _ => {
            let response = CreateInteractionResponseMessage::new()
                .content("Unknown subcommand. Use `/share add`, `/share remove`, `/share list`, or `/share available`.")
                .ephemeral(true);
            let _ = command
                .create_response(&ctx.http, CreateInteractionResponse::Message(response))
                .await;
        }
    }
}

async fn handle_add(
    ctx: &Context,
    command: &CommandInteraction,
    wrapper: &WrapperClient,
    user_id: &str,
) {
    // Extract target user from subcommand options using pattern matching for Serenity 0.12
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

    // Get the user ID from the "user" option
    let target_user_id = sub_opts
        .iter()
        .find(|o| o.name == "user")
        .and_then(|o| o.value.as_user_id());

    let Some(target_id_value) = target_user_id else {
        let response = CreateInteractionResponseMessage::new()
            .content("Please specify a user to share with.")
            .ephemeral(true);
        let _ = command
            .create_response(&ctx.http, CreateInteractionResponse::Message(response))
            .await;
        return;
    };

    // Get resolved user data from command.data.resolved
    let target_user = command.data.resolved.users.get(&target_id_value);
    let target_id = target_id_value.to_string();
    let target_name = target_user.map(|u| u.name.clone()).unwrap_or_else(|| target_id.clone());

    // Don't allow sharing with yourself
    if target_id == user_id {
        let response = CreateInteractionResponseMessage::new()
            .content("You already have access to your own wrapper!")
            .ephemeral(true);
        let _ = command
            .create_response(&ctx.http, CreateInteractionResponse::Message(response))
            .await;
        return;
    }

    match wrapper.share_with(user_id, &target_id).await {
        Ok(result) => {
            let content = format!(
                "**Wrapper Shared**\n\n<@{}> (`{}`) now has access to your wrapper.\n\nThey can use it with:\n`/task prompt:\"...\" target:@{}`\n\n**Currently shared with:** {} user(s)",
                target_id,
                target_name,
                command.user.name,
                result.shared_with.len()
            );
            let response = CreateInteractionResponseMessage::new()
                .content(content)
                .ephemeral(false);
            if let Err(e) = command
                .create_response(&ctx.http, CreateInteractionResponse::Message(response))
                .await
            {
                error!("Failed to send share confirmation: {}", e);
            }
        }
        Err(e) => {
            error!("Failed to share wrapper: {}", e);
            let response = CreateInteractionResponseMessage::new()
                .content(format!("Failed to share wrapper: {}", e))
                .ephemeral(true);
            let _ = command
                .create_response(&ctx.http, CreateInteractionResponse::Message(response))
                .await;
        }
    }
}

async fn handle_remove(
    ctx: &Context,
    command: &CommandInteraction,
    wrapper: &WrapperClient,
    user_id: &str,
) {
    // Extract target user from subcommand options using pattern matching for Serenity 0.12
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

    // Get the user ID from the "user" option
    let target_user_id = sub_opts
        .iter()
        .find(|o| o.name == "user")
        .and_then(|o| o.value.as_user_id());

    let Some(target_id_value) = target_user_id else {
        let response = CreateInteractionResponseMessage::new()
            .content("Please specify a user to remove.")
            .ephemeral(true);
        let _ = command
            .create_response(&ctx.http, CreateInteractionResponse::Message(response))
            .await;
        return;
    };

    // Get resolved user data from command.data.resolved
    let target_user = command.data.resolved.users.get(&target_id_value);
    let target_id = target_id_value.to_string();
    let target_name = target_user.map(|u| u.name.clone()).unwrap_or_else(|| target_id.clone());

    match wrapper.unshare_with(user_id, &target_id).await {
        Ok(result) => {
            let content = format!(
                "**Access Removed**\n\n<@{}> (`{}`) no longer has access to your wrapper.\n\n**Currently shared with:** {} user(s)",
                target_id,
                target_name,
                result.shared_with.len()
            );
            let response = CreateInteractionResponseMessage::new()
                .content(content)
                .ephemeral(false);
            if let Err(e) = command
                .create_response(&ctx.http, CreateInteractionResponse::Message(response))
                .await
            {
                error!("Failed to send unshare confirmation: {}", e);
            }
        }
        Err(e) => {
            error!("Failed to unshare wrapper: {}", e);
            let response = CreateInteractionResponseMessage::new()
                .content(format!("Failed to remove access: {}", e))
                .ephemeral(true);
            let _ = command
                .create_response(&ctx.http, CreateInteractionResponse::Message(response))
                .await;
        }
    }
}

async fn handle_list(
    ctx: &Context,
    command: &CommandInteraction,
    wrapper: &WrapperClient,
    user_id: &str,
) {
    match wrapper.list_shared(user_id).await {
        Ok(result) => {
            let content = if result.shared_with.is_empty() {
                "**Your Wrapper Sharing**\n\nYou haven't shared your wrapper with anyone.\n\nUse `/share add user:@someone` to grant access.".to_string()
            } else {
                let users: Vec<String> = result
                    .shared_with
                    .iter()
                    .map(|id| format!("- <@{}>", id))
                    .collect();
                format!(
                    "**Your Wrapper Sharing**\n\nYour wrapper is shared with {} user(s):\n{}",
                    result.shared_with.len(),
                    users.join("\n")
                )
            };

            let response = CreateInteractionResponseMessage::new()
                .content(content)
                .ephemeral(false);
            if let Err(e) = command
                .create_response(&ctx.http, CreateInteractionResponse::Message(response))
                .await
            {
                error!("Failed to send share list: {}", e);
            }
        }
        Err(e) => {
            error!("Failed to list shared users: {}", e);
            let response = CreateInteractionResponseMessage::new()
                .content(format!("Failed to list shared users: {}", e))
                .ephemeral(true);
            let _ = command
                .create_response(&ctx.http, CreateInteractionResponse::Message(response))
                .await;
        }
    }
}

async fn handle_available(
    ctx: &Context,
    command: &CommandInteraction,
    wrapper: &WrapperClient,
    user_id: &str,
) {
    match wrapper.list_accessible_wrappers(user_id).await {
        Ok(result) => {
            let content = if result.wrappers.is_empty() {
                "**Available Wrappers**\n\nNo wrappers available.\n\nUse `/register local` to set up your own wrapper.".to_string()
            } else {
                let mut lines = vec!["**Available Wrappers**\n".to_string()];
                for w in result.wrappers {
                    let label = if w.is_own {
                        format!("- **Your wrapper** (<@{}>)", w.owner_id)
                    } else {
                        let name = if w.owner_name.is_empty() {
                            w.owner_id.clone()
                        } else {
                            w.owner_name.clone()
                        };
                        format!("- <@{}> (`{}`)", w.owner_id, name)
                    };
                    lines.push(label);
                }
                lines.push("\nTo use someone else's wrapper:".to_string());
                lines.push("`/task prompt:\"...\" target:@username`".to_string());
                lines.join("\n")
            };

            let response = CreateInteractionResponseMessage::new()
                .content(content)
                .ephemeral(false);
            if let Err(e) = command
                .create_response(&ctx.http, CreateInteractionResponse::Message(response))
                .await
            {
                error!("Failed to send available wrappers: {}", e);
            }
        }
        Err(e) => {
            error!("Failed to list accessible wrappers: {}", e);
            let response = CreateInteractionResponseMessage::new()
                .content(format!("Failed to list accessible wrappers: {}", e))
                .ephemeral(true);
            let _ = command
                .create_response(&ctx.http, CreateInteractionResponse::Message(response))
                .await;
        }
    }
}
