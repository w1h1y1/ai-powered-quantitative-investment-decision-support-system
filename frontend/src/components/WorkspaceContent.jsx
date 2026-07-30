import Icon from './Icon'

export default function WorkspaceContent({ content }) {
  return (
    <main className="main-content">
      <section className="content-canvas" aria-labelledby="workspace-title" aria-live="polite">
        <div className="canvas-icon" aria-hidden="true">
          <Icon name={content.icon} />
        </div>
        <p className="eyebrow">{content.eyebrow}</p>
        <h2 id="workspace-title">{content.title}</h2>
        <p>{content.description}</p>
      </section>
    </main>
  )
}
