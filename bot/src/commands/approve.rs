//! /approve command - Submit approval for a task requiring human intervention.

use serenity::all::{
    CommandInteraction, CommandOptionType, Context, CreateCommand, CreateCommandOption,
    CreateInteractionResponse, CreateInteractionResponseMessage, EditInteractionResponse,
};
use tracing::{error, info};

use crate::client::{ApprovalSubmission, TaskStatus, WrapperClient};

/// Create the command registration.
pub fn register() -> CreateCommand {
    CreateCommand::new("approve")
        .description("Submit approval for a task requiring human intervention")
        .add_option(
            CreateCommandOption::new(
                CommandOptionType::String,
                "task_id",
                "The task ID requiring approval",
            )
            .required(true),
        )
        .add_option(
            CreateCommandOption::new(
                CommandOptionType::String,
                "option",
                "The approval option to select",
            )
            .required(true),
        )
        .add_option(
            CreateCommandOption::new(
                CommandOptionType::String,
                "response",
                "Optional custom response text",
            )
            .required(false),
        )
}

/// Handle the /approve command.
pub async fn approve(ctx: &Context, command: &CommandInteraction, wrapper: &WrapperClient) {
    // Get user ID from Discord (server-side, cannot be spoofed)
    let user_id = command.user.id.to_string();

    // Extract options
    let task_id = command
        .data
        .options
        .iter()
        .find(|opt| opt.name == "task_id")
        .and_then(|opt| opt.value.as_str())
        .unwrap_or("");

    let option_id = command
        .data
        .options
        .iter()
        .find(|opt| opt.name == "option")
        .and_then(|opt| opt.value.as_str())
        .unwrap_or("");

    let custom_response = command
        .data
        .options
        .iter()
        .find(|opt| opt.name == "response")
        .and_then(|opt| opt.value.as_str())
        .map(|s| s.to_string());

    info!(
        "Approve command received: task_id='{}', option='{}', user={}, custom={:?}",
        task_id, option_id, user_id, custom_response
    );

    // Send initial "processing" response
    let initial_response = CreateInteractionResponseMessage::new()
        .content("⏳ Processing approval...")
        .ephemeral(false);

    if let Err(e) = command
        .create_response(&ctx.http, CreateInteractionResponse::Message(initial_response))
        .await
    {
        error!("Failed to send initial response: {}", e);
        return;
    }

    // Submit approval
    let submission = ApprovalSubmission {
        option_id: option_id.to_string(),
        custom_response,
    };

    match wrapper.submit_approval(task_id, &user_id, submission).await {
        Ok(response) => {
            let status_emoji = match response.status {
                TaskStatus::Completed => "✅",
                TaskStatus::Failed => "❌",
                TaskStatus::Running => "🔄",
                TaskStatus::Pending => "⏳",
                TaskStatus::NeedsApproval => "⚠️",
            };

            let mut content = format!(
                "{} **Approval Processed**\n\n**Status:** {}\n**Task ID:** `{}`",
                status_emoji, response.status, response.task_id,
            );

            // Add output if present
            if !response.output.is_empty() {
                let output = if response.output.len() > 1800 {
                    format!("{}...\n(truncated)", &response.output[..1800])
                } else {
                    response.output.clone()
                };
                content.push_str(&format!("\n\n**Output:**\n```\n{}\n```", output));
            }

            // Add error if present
            if let Some(err) = &response.error {
                content.push_str(&format!("\n\n**Error:**\n```\n{}\n```", err));
            }

            // Check if more approval is needed
            if let Some(approval) = &response.approval_request {
                content.push_str(&format!(
                    "\n\n**Additional Approval Required:**\n{}\n\nUse `/approve task_id:{} option:<option>` to respond.",
                    approval.description,
                    response.task_id,
                ));
            }

            let edit = EditInteractionResponse::new().content(content);
            if let Err(e) = command.edit_response(&ctx.http, edit).await {
                error!("Failed to edit response: {}", e);
            }
        }
        Err(e) => {
            error!("Approval submission failed: {}", e);
            let edit = EditInteractionResponse::new()
                .content(format!("❌ **Approval Failed**\n\n```\n{}\n```", e));
            if let Err(e) = command.edit_response(&ctx.http, edit).await {
                error!("Failed to edit error response: {}", e);
            }
        }
    }
}
