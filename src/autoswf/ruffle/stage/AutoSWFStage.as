package {
    import flash.display.Loader;
    import flash.display.MovieClip;
    import flash.events.Event;
    import flash.system.ApplicationDomain;
    import flash.system.LoaderContext;
    import flash.utils.ByteArray;

    /** AutoSWF's test stage for Ruffle. It stands in for AQW's Game root (stage.getChildAt(0)): it has the world's
     *  flags and mcSetColor, loads the embedded armor and puts its animated head on an avatar stand-in. */
    public class AutoSWFStage extends MovieClip {
        public var world:Object = {bitWalk: true};
        public var settings:Object;
        public var avatar:MovieClip;
        private var loader:Loader;
        private var frames:int = 0;

        public function AutoSWFStage() {
            super();
            var json:ByteArray = new AutoSWFStageSettings();
            settings = JSON.parse(json.readUTFBytes(json.length));
            var armor:ByteArray = new AutoSWFArmorBytes();
            var context:LoaderContext = new LoaderContext(false, ApplicationDomain.currentDomain);
            context.allowCodeImport = true;
            loader = new Loader();
            loader.contentLoaderInfo.addEventListener(Event.COMPLETE, onArmor);
            loader.loadBytes(armor, context);
            log("loading the armor, " + armor.length + " bytes");
        }

        private function onArmor(e:Event):void {
            var link:String = settings.link;
            var gender:String = settings.genders[0];
            var domain:ApplicationDomain = loader.contentLoaderInfo.applicationDomain;
            var Head:Class = domain.getDefinition(link + gender + "Head") as Class;
            var events:Object = {};
            avatar = new MovieClip();
            avatar.animEvents = events;
            avatar.addAnimationListener = function (label:String, fn:Function, block:Boolean = false):void {
                if (events[label] == null) events[label] = [];
                events[label].push([fn, block]);
            };
            var skeleton:MovieClip = new MovieClip();
            skeleton.name = "mcChar";
            for each (var name:String in ["backhair", "cape", "weapon"]) {
                var slot:MovieClip = new MovieClip();
                slot.name = name;
                skeleton.addChild(slot);
            }
            var head:MovieClip = new MovieClip();
            head.name = "head";
            for each (name in ["hair", "helm"]) {
                var part:MovieClip = new MovieClip();
                part.name = name;
                head.addChild(part);
            }
            skeleton.addChild(head);
            avatar.mcChar = skeleton;
            avatar.addChild(skeleton);
            avatar.x = 380;
            avatar.y = 420;
            addChild(avatar);
            var face:MovieClip = new Head() as MovieClip;
            face.name = "face";
            head.addChildAt(face, 0);
            var count:int = 0;
            for (var label:String in events) count++;
            log("armor head added, " + count + " game labels listened");
            addEventListener(Event.ENTER_FRAME, onFrame);
        }

        private function onFrame(e:Event):void {
            if (++frames < 3) return;
            removeEventListener(Event.ENTER_FRAME, onFrame);
            var face:MovieClip = avatar.mcChar.getChildByName("head").getChildByName("face") as MovieClip;
            log("head label " + face.currentLabel + ", frame " + face.currentFrame);
            log("DONE");
        }

        public function mcSetColor(clip:MovieClip, location:String, shade:String):void {
        }

        private function log(text:String):void {
            trace("AUTOSWF " + text);
        }
    }
}
