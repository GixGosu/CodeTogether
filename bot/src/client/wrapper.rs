//! HTTP client for communicating with the Claude wrapper service.

use anyhow::{Context, Result};
use reqwest::Client;
use serde::{Deserialize, Serialize};

/// Task status enum matching the wrapper service.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum TaskStatus {
    Pending,
    Running,
    Completed,
    Failed,
    #[serde(rename = "needs_approval")]
    NeedsApproval,
}

impl std::fmt::Display for TaskStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            TaskStatus::Pending => write!(f, "Pending"),
            TaskStatus::Running => write!(f, "Running"),
            TaskStatus::Completed => write!(f, "Completed"),
            TaskStatus::Failed => write!(f, "Failed"),
            TaskStatus::NeedsApproval => write!(f, "Needs Approval"),
        }
    }
}

/// Execution mode for tasks.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum ExecutionMode {
    Local,
    Cluster,
}

/// Request to create a new task.
#[derive(Debug, Serialize)]
pub struct TaskRequest {
    pub prompt: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub session_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub project: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub working_dir: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub discord_user_id: Option<String>,
    /// Target user's wrapper to use for collaborative access.
    /// Requires the target user to have shared their wrapper with you.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub target_user_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mode: Option<ExecutionMode>,
}

/// Request to add a new project.
#[derive(Debug, Serialize)]
pub struct ProjectRequest {
    pub name: String,
    pub path: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    pub discord_user_id: String,
}

/// Project information.
#[derive(Debug, Clone, Deserialize)]
pub struct ProjectResponse {
    pub name: String,
    pub path: String,
    pub description: String,
    pub owner_id: String,
    pub created_at: String,
}

/// Request to register a local wrapper.
#[derive(Debug, Serialize)]
pub struct RegisterLocalRequest {
    pub discord_id: String,
    pub discord_name: String,
    pub wrapper_url: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub auth_token: Option<String>,
}

/// Request to enable cluster access.
#[derive(Debug, Serialize)]
pub struct EnableClusterRequest {
    pub discord_id: String,
    pub discord_name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub storage_path: Option<String>,
}

/// Request to set default mode.
#[derive(Debug, Serialize)]
pub struct SetModeRequest {
    pub mode: ExecutionMode,
}

/// User information.
#[derive(Debug, Clone, Deserialize)]
pub struct UserResponse {
    pub discord_id: String,
    pub discord_name: String,
    pub local_wrapper_url: Option<String>,
    pub cluster_enabled: bool,
    pub cluster_storage_path: Option<String>,
    pub default_mode: String,
    pub created_at: String,
    pub last_seen: String,
}

/// Approval option from the wrapper service.
#[derive(Debug, Clone, Deserialize)]
pub struct ApprovalOption {
    pub id: String,
    pub label: String,
    pub description: Option<String>,
}

/// Approval request requiring human intervention.
#[derive(Debug, Clone, Deserialize)]
pub struct ApprovalRequest {
    pub action: String,
    pub description: String,
    pub options: Vec<ApprovalOption>,
}

/// Response from task operations.
#[derive(Debug, Clone, Deserialize)]
pub struct TaskResponse {
    pub task_id: String,
    pub session_id: String,
    pub status: TaskStatus,
    pub output: String,
    pub error: Option<String>,
    pub approval_request: Option<ApprovalRequest>,
    pub created_at: String,
    pub updated_at: String,
}

/// Submission of an approval response.
#[derive(Debug, Serialize)]
pub struct ApprovalSubmission {
    pub option_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub custom_response: Option<String>,
}

/// Session information.
#[derive(Debug, Deserialize)]
pub struct SessionInfo {
    pub session_id: String,
    pub task_count: i32,
    pub created_at: String,
    pub last_activity: String,
    pub status: String,
}

/// Health check response.
#[derive(Debug, Deserialize)]
pub struct HealthResponse {
    pub status: String,
    pub version: String,
    pub uptime_seconds: f64,
}

// =============================================================================
// Collaborative Sharing
// =============================================================================

/// Request to share wrapper access.
#[derive(Debug, Serialize)]
pub struct ShareRequest {
    pub target_user_id: String,
}

/// Response listing shared users.
#[derive(Debug, Deserialize)]
pub struct ShareListResponse {
    pub shared_with: Vec<String>,
}

/// A wrapper the user can access.
#[derive(Debug, Clone, Deserialize)]
pub struct AccessibleWrapper {
    pub owner_id: String,
    pub owner_name: String,
    pub is_own: bool,
}

/// Response listing accessible wrappers.
#[derive(Debug, Deserialize)]
pub struct AccessibleWrappersResponse {
    pub wrappers: Vec<AccessibleWrapper>,
}

/// HTTP client for the wrapper service.
#[derive(Debug, Clone)]
pub struct WrapperClient {
    client: Client,
    base_url: String,
}

impl WrapperClient {
    /// Create a new wrapper client.
    pub fn new(base_url: &str) -> Self {
        Self {
            client: Client::new(),
            base_url: base_url.trim_end_matches('/').to_string(),
        }
    }

    /// Check if the wrapper service is healthy.
    pub async fn health_check(&self) -> Result<HealthResponse> {
        let url = format!("{}/api/v1/health", self.base_url);
        let response = self
            .client
            .get(&url)
            .send()
            .await
            .context("Failed to connect to wrapper service")?;

        response
            .json()
            .await
            .context("Failed to parse health response")
    }

    /// Submit a new task to the wrapper service.
    pub async fn submit_task(&self, request: TaskRequest) -> Result<TaskResponse> {
        let url = format!("{}/api/v1/tasks", self.base_url);
        let response = self
            .client
            .post(&url)
            .json(&request)
            .send()
            .await
            .context("Failed to submit task")?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            anyhow::bail!("Task submission failed ({}): {}", status, body);
        }

        response
            .json()
            .await
            .context("Failed to parse task response")
    }

    /// Get the status of a task.
    ///
    /// The `user_id` is required when talking to the orchestrator to ensure
    /// the request is routed to the correct user's wrapper.
    pub async fn get_task(&self, task_id: &str, user_id: &str) -> Result<TaskResponse> {
        let url = format!(
            "{}/api/v1/tasks/{}?discord_user_id={}",
            self.base_url, task_id, user_id
        );
        let response = self
            .client
            .get(&url)
            .send()
            .await
            .context("Failed to get task")?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            anyhow::bail!("Failed to get task ({}): {}", status, body);
        }

        response
            .json()
            .await
            .context("Failed to parse task response")
    }

    /// Submit an approval response for a task.
    ///
    /// The `user_id` is required when talking to the orchestrator to ensure
    /// the request is routed to the correct user's wrapper.
    pub async fn submit_approval(
        &self,
        task_id: &str,
        user_id: &str,
        submission: ApprovalSubmission,
    ) -> Result<TaskResponse> {
        let url = format!(
            "{}/api/v1/tasks/{}/approve?discord_user_id={}",
            self.base_url, task_id, user_id
        );
        let response = self
            .client
            .post(&url)
            .json(&submission)
            .send()
            .await
            .context("Failed to submit approval")?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            anyhow::bail!("Approval submission failed ({}): {}", status, body);
        }

        response
            .json()
            .await
            .context("Failed to parse approval response")
    }

    /// List all active sessions.
    pub async fn list_sessions(&self) -> Result<Vec<SessionInfo>> {
        let url = format!("{}/api/v1/sessions", self.base_url);
        let response = self
            .client
            .get(&url)
            .send()
            .await
            .context("Failed to list sessions")?;

        response
            .json()
            .await
            .context("Failed to parse sessions response")
    }

    /// Terminate a session.
    pub async fn terminate_session(&self, session_id: &str) -> Result<()> {
        let url = format!("{}/api/v1/sessions/{}", self.base_url, session_id);
        let response = self
            .client
            .delete(&url)
            .send()
            .await
            .context("Failed to terminate session")?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            anyhow::bail!("Session termination failed ({}): {}", status, body);
        }

        Ok(())
    }

    /// List all registered projects for a user.
    pub async fn list_projects(&self, discord_user_id: &str) -> Result<Vec<ProjectResponse>> {
        let url = format!("{}/api/v1/projects/{}", self.base_url, discord_user_id);
        let response = self
            .client
            .get(&url)
            .send()
            .await
            .context("Failed to list projects")?;

        response
            .json()
            .await
            .context("Failed to parse projects response")
    }

    /// Add a new project.
    pub async fn add_project(&self, request: ProjectRequest) -> Result<ProjectResponse> {
        let url = format!("{}/api/v1/projects", self.base_url);
        let response = self
            .client
            .post(&url)
            .json(&request)
            .send()
            .await
            .context("Failed to add project")?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            anyhow::bail!("Failed to add project ({}): {}", status, body);
        }

        response
            .json()
            .await
            .context("Failed to parse project response")
    }

    /// Remove a project for a user.
    pub async fn remove_project(&self, discord_user_id: &str, name: &str) -> Result<()> {
        let url = format!("{}/api/v1/projects/{}/{}", self.base_url, discord_user_id, name);
        let response = self
            .client
            .delete(&url)
            .send()
            .await
            .context("Failed to remove project")?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            anyhow::bail!("Failed to remove project ({}): {}", status, body);
        }

        Ok(())
    }

    // =========================================================================
    // User Management
    // =========================================================================

    /// Get a user by Discord ID.
    pub async fn get_user(&self, discord_id: &str) -> Result<UserResponse> {
        let url = format!("{}/api/v1/users/{}", self.base_url, discord_id);
        let response = self
            .client
            .get(&url)
            .send()
            .await
            .context("Failed to get user")?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            anyhow::bail!("Failed to get user ({}): {}", status, body);
        }

        response
            .json()
            .await
            .context("Failed to parse user response")
    }

    /// Register a local wrapper for a user.
    pub async fn register_local(&self, request: RegisterLocalRequest) -> Result<UserResponse> {
        let url = format!("{}/api/v1/users/register-local", self.base_url);
        let response = self
            .client
            .post(&url)
            .json(&request)
            .send()
            .await
            .context("Failed to register local wrapper")?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            anyhow::bail!("Failed to register local wrapper ({}): {}", status, body);
        }

        response
            .json()
            .await
            .context("Failed to parse user response")
    }

    /// Unregister a user's local wrapper.
    pub async fn unregister_local(&self, discord_id: &str) -> Result<()> {
        let url = format!("{}/api/v1/users/{}/local", self.base_url, discord_id);
        let response = self
            .client
            .delete(&url)
            .send()
            .await
            .context("Failed to unregister local wrapper")?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            anyhow::bail!("Failed to unregister local wrapper ({}): {}", status, body);
        }

        Ok(())
    }

    /// Enable cluster access for a user.
    pub async fn enable_cluster(&self, request: EnableClusterRequest) -> Result<UserResponse> {
        let url = format!("{}/api/v1/users/enable-cluster", self.base_url);
        let response = self
            .client
            .post(&url)
            .json(&request)
            .send()
            .await
            .context("Failed to enable cluster access")?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            anyhow::bail!("Failed to enable cluster access ({}): {}", status, body);
        }

        response
            .json()
            .await
            .context("Failed to parse user response")
    }

    /// Set user's default execution mode.
    pub async fn set_user_mode(&self, discord_id: &str, mode: ExecutionMode) -> Result<UserResponse> {
        let url = format!("{}/api/v1/users/{}/set-mode", self.base_url, discord_id);
        let request = SetModeRequest { mode };
        let response = self
            .client
            .post(&url)
            .json(&request)
            .send()
            .await
            .context("Failed to set user mode")?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            anyhow::bail!("Failed to set user mode ({}): {}", status, body);
        }

        response
            .json()
            .await
            .context("Failed to parse user response")
    }

    // =========================================================================
    // Collaborative Sharing
    // =========================================================================

    /// Share wrapper access with another user.
    pub async fn share_with(&self, owner_id: &str, target_id: &str) -> Result<ShareListResponse> {
        let url = format!("{}/api/v1/users/{}/share", self.base_url, owner_id);
        let request = ShareRequest {
            target_user_id: target_id.to_string(),
        };
        let response = self
            .client
            .post(&url)
            .json(&request)
            .send()
            .await
            .context("Failed to share wrapper")?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            anyhow::bail!("Failed to share wrapper ({}): {}", status, body);
        }

        response
            .json()
            .await
            .context("Failed to parse share response")
    }

    /// Remove wrapper sharing with another user.
    pub async fn unshare_with(&self, owner_id: &str, target_id: &str) -> Result<ShareListResponse> {
        let url = format!(
            "{}/api/v1/users/{}/share/{}",
            self.base_url, owner_id, target_id
        );
        let response = self
            .client
            .delete(&url)
            .send()
            .await
            .context("Failed to unshare wrapper")?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            anyhow::bail!("Failed to unshare wrapper ({}): {}", status, body);
        }

        response
            .json()
            .await
            .context("Failed to parse unshare response")
    }

    /// List users the wrapper is shared with.
    pub async fn list_shared(&self, owner_id: &str) -> Result<ShareListResponse> {
        let url = format!("{}/api/v1/users/{}/share", self.base_url, owner_id);
        let response = self
            .client
            .get(&url)
            .send()
            .await
            .context("Failed to list shared users")?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            anyhow::bail!("Failed to list shared users ({}): {}", status, body);
        }

        response
            .json()
            .await
            .context("Failed to parse share list response")
    }

    /// List all wrappers the user can access.
    pub async fn list_accessible_wrappers(&self, user_id: &str) -> Result<AccessibleWrappersResponse> {
        let url = format!(
            "{}/api/v1/users/{}/accessible-wrappers",
            self.base_url, user_id
        );
        let response = self
            .client
            .get(&url)
            .send()
            .await
            .context("Failed to list accessible wrappers")?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            anyhow::bail!("Failed to list accessible wrappers ({}): {}", status, body);
        }

        response
            .json()
            .await
            .context("Failed to parse accessible wrappers response")
    }
}
