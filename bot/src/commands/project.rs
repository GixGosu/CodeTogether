//! /project command - Manage registered projects (per-user isolated).

use serenity::all::{
    CommandInteraction, CommandOptionType, Context, CreateCommand, CreateCommandOption,
    CreateInteractionResponse, CreateInteractionResponseMessage,
};
use tracing::{error, info};

use crate::client::{ProjectRequest, WrapperClient};

/// Create the command registration.
pub fn register() -> CreateCommand {
    CreateCommand::new("project")
        .description("Manage your registered projects")
        .add_option(
            CreateCommandOption::new(
                CommandOptionType::SubCommand,
                "list",
                "List your registered projects",
            ),
        )
        .add_option(
            CreateCommandOption::new(
                CommandOptionType::SubCommand,
                "add",
                "Add a new project",
            )
            .add_sub_option(
                CreateCommandOption::new(
                    CommandOptionType::String,
                    "name",
                    "Unique project name/alias (e.g., 'my-api')",
                )
                .required(true),
            )
            .add_sub_option(
                CreateCommandOption::new(
                    CommandOptionType::String,
                    "path",
                    "Absolute path to the project directory",
                )
                .required(true),
            )
            .add_sub_option(
                CreateCommandOption::new(
                    CommandOptionType::String,
                    "description",
                    "Optional project description",
                )
                .required(false),
            ),
        )
        .add_option(
            CreateCommandOption::new(
                CommandOptionType::SubCommand,
                "remove",
                "Remove a project",
            )
            .add_sub_option(
                CreateCommandOption::new(
                    CommandOptionType::String,
                    "name",
                    "Project name to remove",
                )
                .required(true),
            ),
        )
}

/// Handle the /project command.
pub async fn project(ctx: &Context, command: &CommandInteraction, wrapper: &WrapperClient) {
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
        "Project command received: subcommand='{}', user={}",
        subcommand, user_id
    );

    match subcommand {
        "list" => handle_list(ctx, command, wrapper, &user_id).await,
        "add" => handle_add(ctx, command, wrapper, &user_id).await,
        "remove" => handle_remove(ctx, command, wrapper, &user_id).await,
        _ => {
            let response = CreateInteractionResponseMessage::new()
                .content("Unknown subcommand. Use `/project list`, `/project add`, or `/project remove`.")
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
    match wrapper.list_projects(user_id).await {
        Ok(projects) => {
            let content = if projects.is_empty() {
                "**Your Projects:**\n\nNo projects registered.\n\nUse `/project add name:<name> path:<path>` to add one.".to_string()
            } else {
                let mut lines = vec!["**Your Projects:**\n".to_string()];
                for p in projects {
                    let desc = if p.description.is_empty() {
                        String::new()
                    } else {
                        format!(" - {}", p.description)
                    };
                    lines.push(format!("`{}` → `{}`{}", p.name, p.path, desc));
                }
                lines.join("\n")
            };

            let response = CreateInteractionResponseMessage::new()
                .content(content)
                .ephemeral(false);
            if let Err(e) = command
                .create_response(&ctx.http, CreateInteractionResponse::Message(response))
                .await
            {
                error!("Failed to send project list: {}", e);
            }
        }
        Err(e) => {
            error!("Failed to list projects: {}", e);
            let response = CreateInteractionResponseMessage::new()
                .content(format!("❌ Failed to list projects: {}", e))
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
    // Extract subcommand options using pattern matching for Serenity 0.12
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

    let name = sub_opts
        .iter()
        .find(|o| o.name == "name")
        .and_then(|o| o.value.as_str())
        .unwrap_or("");

    let path = sub_opts
        .iter()
        .find(|o| o.name == "path")
        .and_then(|o| o.value.as_str())
        .unwrap_or("");

    let description: Option<String> = sub_opts
        .iter()
        .find(|o| o.name == "description")
        .and_then(|o| o.value.as_str())
        .map(|s| s.to_string());

    if name.is_empty() || path.is_empty() {
        let response = CreateInteractionResponseMessage::new()
            .content("❌ Both `name` and `path` are required.")
            .ephemeral(true);
        let _ = command
            .create_response(&ctx.http, CreateInteractionResponse::Message(response))
            .await;
        return;
    }

    let request = ProjectRequest {
        name: name.to_string(),
        path: path.to_string(),
        description,
        discord_user_id: user_id.to_string(),
    };

    match wrapper.add_project(request).await {
        Ok(project) => {
            let content = format!(
                "✅ **Project Added**\n\n**Name:** `{}`\n**Path:** `{}`\n\nUse `/task prompt:\"...\" project:{}` to work on this project.",
                project.name, project.path, project.name
            );
            let response = CreateInteractionResponseMessage::new()
                .content(content)
                .ephemeral(false);
            if let Err(e) = command
                .create_response(&ctx.http, CreateInteractionResponse::Message(response))
                .await
            {
                error!("Failed to send add confirmation: {}", e);
            }
        }
        Err(e) => {
            error!("Failed to add project: {}", e);
            let response = CreateInteractionResponseMessage::new()
                .content(format!("❌ Failed to add project: {}", e))
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
    // Extract subcommand options using pattern matching for Serenity 0.12
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

    let name = sub_opts
        .iter()
        .find(|o| o.name == "name")
        .and_then(|o| o.value.as_str())
        .unwrap_or("");

    if name.is_empty() {
        let response = CreateInteractionResponseMessage::new()
            .content("❌ Project `name` is required.")
            .ephemeral(true);
        let _ = command
            .create_response(&ctx.http, CreateInteractionResponse::Message(response))
            .await;
        return;
    }

    match wrapper.remove_project(user_id, name).await {
        Ok(()) => {
            let content = format!("✅ Project `{}` has been removed.", name);
            let response = CreateInteractionResponseMessage::new()
                .content(content)
                .ephemeral(false);
            if let Err(e) = command
                .create_response(&ctx.http, CreateInteractionResponse::Message(response))
                .await
            {
                error!("Failed to send remove confirmation: {}", e);
            }
        }
        Err(e) => {
            error!("Failed to remove project: {}", e);
            let response = CreateInteractionResponseMessage::new()
                .content(format!("❌ Failed to remove project: {}", e))
                .ephemeral(true);
            let _ = command
                .create_response(&ctx.http, CreateInteractionResponse::Message(response))
                .await;
        }
    }
}
