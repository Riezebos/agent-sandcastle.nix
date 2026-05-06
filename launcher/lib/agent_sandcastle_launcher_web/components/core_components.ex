defmodule AgentSandcastleLauncherWeb.CoreComponents do
  use Phoenix.Component

  attr :flash, :map, required: true

  def flash_group(assigns) do
    ~H"""
    <div class="flash-stack">
      <p :if={msg = Phoenix.Flash.get(@flash, :info)} class="flash info"><%= msg %></p>
      <p :if={msg = Phoenix.Flash.get(@flash, :error)} class="flash error"><%= msg %></p>
    </div>
    """
  end

  attr :changeset, Ecto.Changeset, required: true
  attr :field, :atom, required: true

  def error(assigns) do
    assigns =
      assign(assigns, :errors, Keyword.get_values(assigns.changeset.errors, assigns.field))

    ~H"""
    <p :for={{message, _opts} <- @errors} class="field-error"><%= message %></p>
    """
  end
end
