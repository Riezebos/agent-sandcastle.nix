defmodule AgentSandcastleLauncherWeb.Router do
  use AgentSandcastleLauncherWeb, :router

  pipeline :browser do
    plug :accepts, ["html"]
    plug :fetch_session
    plug :fetch_live_flash
    plug :put_root_layout, html: {AgentSandcastleLauncherWeb.Layouts, :root}
    plug :protect_from_forgery
    plug :put_secure_browser_headers
  end

  scope "/", AgentSandcastleLauncherWeb do
    pipe_through :browser

    live "/", DashboardLive, :index
    live "/sandboxes/new", SandboxNewLive, :new
    live "/sandboxes/:id", SandboxShowLive, :show
  end
end
