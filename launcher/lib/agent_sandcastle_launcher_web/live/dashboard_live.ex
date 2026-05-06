defmodule AgentSandcastleLauncherWeb.DashboardLive do
  use AgentSandcastleLauncherWeb, :live_view

  alias AgentSandcastleLauncher.Sandboxes

  @impl true
  def mount(_params, _session, socket) do
    {:ok, assign(socket, sandboxes: Sandboxes.list_sandboxes())}
  end

  @impl true
  def render(assigns) do
    ~H"""
    <section class="grid">
      <div>
        <h1>Sandboxes</h1>
        <p class="muted">Dry-run records only. No systemd or microVM lifecycle calls are made.</p>
      </div>

      <%= if @sandboxes == [] do %>
        <div class="panel">
          <p class="muted">No sandboxes yet.</p>
          <a class="button" href={~p"/sandboxes/new"}>Create Sandbox</a>
        </div>
      <% else %>
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Repo</th>
              <th>Agent</th>
              <th>Happy Session</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            <tr :for={sandbox <- @sandboxes}>
              <td><a href={~p"/sandboxes/#{sandbox.id}"}><%= sandbox.name %></a></td>
              <td>
                <div><%= sandbox.repo_url %></div>
                <div class="muted"><%= sandbox.branch %></div>
              </td>
              <td><%= sandbox.agent_key %></td>
              <td><%= sandbox.happy_session_name %></td>
              <td class="status"><%= sandbox.status %></td>
            </tr>
          </tbody>
        </table>
      <% end %>
    </section>
    """
  end
end
