defmodule AgentSandcastleLauncherWeb.SandboxShowLive do
  use AgentSandcastleLauncherWeb, :live_view

  alias AgentSandcastleLauncher.Sandboxes

  @impl true
  def mount(%{"id" => id}, _session, socket) do
    {:ok, assign(socket, sandbox: Sandboxes.get_sandbox!(id))}
  end

  @impl true
  def render(assigns) do
    ~H"""
    <section class="grid">
      <div>
        <a class="button secondary" href={~p"/"}>Back</a>
        <h1><%= @sandbox.name %></h1>
        <p class="muted"><%= @sandbox.repo_url %> on <%= @sandbox.branch %></p>
      </div>

      <div class="grid two-col">
        <div class="panel">
          <h2>Dry-Run VM Parameters</h2>
          <dl>
            <dt>Status</dt>
            <dd class="status"><%= @sandbox.status %></dd>
            <dt>Agent</dt>
            <dd><%= @sandbox.agent_key %> (<%= @sandbox.agent_auth_mode %>)</dd>
            <dt>Happy Session</dt>
            <dd><%= @sandbox.happy_session_name %></dd>
            <dt>QCOW2 Path</dt>
            <dd><%= @sandbox.qcow2_path %></dd>
            <dt>Credential Path</dt>
            <dd><%= @sandbox.agent_credential.staged_path %></dd>
          </dl>
        </div>

        <div class="panel">
          <h2>Happy</h2>
          <dl>
            <dt>Relay</dt>
            <dd><%= @sandbox.happy_session.relay_url %></dd>
            <dt>Session</dt>
            <dd><%= @sandbox.happy_session.session_name %></dd>
            <dt>Status</dt>
            <dd><%= @sandbox.happy_session.status %></dd>
          </dl>
        </div>
      </div>

      <div class="panel">
        <h2>Rendered VM Spec</h2>
        <pre><%= @sandbox.rendered_vm_spec %></pre>
      </div>
    </section>
    """
  end
end
