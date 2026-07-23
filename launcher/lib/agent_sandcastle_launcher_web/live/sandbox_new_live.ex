defmodule AgentSandcastleLauncherWeb.SandboxNewLive do
  use AgentSandcastleLauncherWeb, :live_view

  alias AgentSandcastleLauncher.Agents.Registry
  alias AgentSandcastleLauncher.Sandboxes

  @impl true
  def mount(_params, session, socket) do
    changeset =
      Sandboxes.change_sandbox_request(%{
        "branch" => "main",
        "agent_key" => "claude-code"
      })

    {:ok,
     socket
     |> assign(:agents, Registry.list())
     |> assign(:actor, get_in(session, ["agent_sandcastle_identity", "username"]))
     |> assign(:form, to_form(changeset, as: :sandbox_request))
     |> assign(:changeset, changeset)}
  end

  @impl true
  def handle_event("validate", %{"sandbox_request" => params}, socket) do
    changeset =
      params
      |> Sandboxes.change_sandbox_request()
      |> Map.put(:action, :validate)

    {:noreply, assign_form(socket, changeset)}
  end

  @impl true
  def handle_event("save", %{"sandbox_request" => params}, socket) do
    case Sandboxes.create_sandbox(params, socket.assigns.actor) do
      {:ok, sandbox} ->
        {:noreply,
         socket
         |> put_flash(:info, "Sandbox dry-run record created.")
         |> push_navigate(to: ~p"/sandboxes/#{sandbox.id}")}

      {:error, changeset} ->
        {:noreply, assign_form(socket, changeset)}
    end
  end

  @impl true
  def render(assigns) do
    ~H"""
    <section class="grid two-col">
      <div>
        <h1>Create Sandbox</h1>
        <p class="muted">This records the intended VM config and leaves lifecycle actions in dry-run mode.</p>
      </div>

      <div class="panel">
        <.form
          for={@form}
          id="sandbox-form"
          phx-change="validate"
          phx-submit="save"
          class="grid"
        >
          <label>
            Repo URL
            <input type="text" name={@form[:repo_url].name} value={@form[:repo_url].value || ""} />
            <.error changeset={@changeset} field={:repo_url} />
          </label>

          <label>
            Branch
            <input type="text" name={@form[:branch].name} value={@form[:branch].value || "main"} />
            <.error changeset={@changeset} field={:branch} />
          </label>

          <label>
            Agent
            <select name={@form[:agent_key].name}>
              <option
                :for={agent <- @agents}
                value={agent.key}
                selected={agent.key == @form[:agent_key].value}
              >
                <%= agent.display_name %>
              </option>
            </select>
            <.error changeset={@changeset} field={:agent_key} />
          </label>

          <p class="muted">
            An opaque credential ID will be generated for this dry run. Host paths are resolved
            only by the trusted lifecycle broker.
          </p>

          <button class="button" type="submit">Create Dry Run</button>
        </.form>
      </div>
    </section>
    """
  end

  defp assign_form(socket, changeset) do
    socket
    |> assign(:changeset, changeset)
    |> assign(:form, to_form(changeset, as: :sandbox_request))
  end
end
